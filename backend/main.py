from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from pathlib import Path
import asyncio
import uuid
import time
import httpx

app = FastAPI(title="Local Agentic AI Pro MVP")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class ServiceSettings(BaseModel):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b"
    embedding_model: str = "nomic-embed-text"
    redis_url: str = "redis://localhost:6379/0"
    searxng_url: str = "http://localhost:8080"


class AgentSettings(BaseModel):
    planner_temperature: float = 0.2
    researcher_temperature: float = 0.7
    executor_temperature: float = 0.2
    critic_temperature: float = 0.2
    max_loop_count: int = 2
    max_steps: int = 10


class RuntimeSettings(BaseModel):
    sandbox_root: str = "./workspace"
    code_exec_timeout_seconds: int = 30
    stream_chunk_delay_ms: int = 50


class ToolConfig(BaseModel):
    enabled: bool = True
    description: str


class AppSettings(BaseModel):
    services: ServiceSettings = ServiceSettings()
    agents: AgentSettings = AgentSettings()
    runtime: RuntimeSettings = RuntimeSettings()
    tools: Dict[str, ToolConfig] = Field(default_factory=lambda: {
        "filesystem": ToolConfig(description="Create/read/write/list files in sandbox"),
        "http": ToolConfig(description="Call HTTP endpoints"),
        "code_executor": ToolConfig(description="Run Python snippets")
    })


class AgentNode(BaseModel):
    id: str
    name: str
    role_prompt: str
    enabled_tools: List[str] = Field(default_factory=list)


class Workflow(BaseModel):
    nodes: List[AgentNode]
    edges: List[Dict[str, str]] = Field(default_factory=list)


class TaskRequest(BaseModel):
    prompt: str
    workflow: Workflow


class FileCreateRequest(BaseModel):
    path: str
    content: str = ""


class FileListRequest(BaseModel):
    path: str = "."


SETTINGS = AppSettings()
TASKS: Dict[str, Dict[str, Any]] = {}
SOCKETS: Dict[str, List[WebSocket]] = {}


def sandbox_root() -> Path:
    root = Path(SETTINGS.runtime.sandbox_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_path(rel_path: str) -> Path:
    candidate = (sandbox_root() / rel_path).resolve()
    if sandbox_root() not in candidate.parents and candidate != sandbox_root():
        raise HTTPException(status_code=400, detail="path escapes sandbox")
    return candidate


async def emit(task_id: str, event: Dict[str, Any]) -> None:
    for ws in SOCKETS.get(task_id, []):
        await ws.send_json(event)


async def simulate_agent(node: AgentNode, prompt: str) -> str:
    await asyncio.sleep(SETTINGS.runtime.stream_chunk_delay_ms / 1000)
    return f"[{node.name}] completed step with tools={node.enabled_tools}: {prompt[:100]}"


async def run_task(task_id: str, request: TaskRequest) -> None:
    TASKS[task_id]["status"] = "running"
    start = time.time()
    outputs = []
    for idx, node in enumerate(request.workflow.nodes, start=1):
        await emit(task_id, {"type": "agent_started", "step": idx, "agent": node.name})
        out = await simulate_agent(node, request.prompt)
        outputs.append(out)
        await emit(task_id, {"type": "agent_output", "step": idx, "agent": node.name, "output": out})
    result = "\n".join(outputs)
    TASKS[task_id].update({"status": "done", "result": result, "duration_seconds": round(time.time() - start, 2)})
    await emit(task_id, {"type": "final_output", "output": result})


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(APP_HTML)


@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings", response_model=AppSettings)
async def get_settings() -> AppSettings:
    return SETTINGS


@app.put("/api/settings", response_model=AppSettings)
async def update_settings(payload: AppSettings) -> AppSettings:
    global SETTINGS
    SETTINGS = payload
    return SETTINGS


@app.get("/api/models")
async def list_ollama_models() -> Dict[str, Any]:
    url = f"{SETTINGS.services.ollama_base_url}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as ex:
        return {"error": str(ex), "models": []}


@app.post("/api/task")
async def create_task(request: TaskRequest) -> Dict[str, str]:
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"id": task_id, "status": "queued", "result": None}
    asyncio.create_task(run_task(task_id, request))
    return {"task_id": task_id}


@app.get("/api/task/{task_id}")
async def task_status(task_id: str) -> Dict[str, Any]:
    return TASKS.get(task_id, {"error": "task not found"})


@app.post("/api/tools/files/create")
async def create_file(req: FileCreateRequest) -> Dict[str, Any]:
    p = safe_path(req.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(req.content, encoding="utf-8")
    return {"ok": True, "path": str(p), "bytes": p.stat().st_size}


@app.post("/api/tools/files/read")
async def read_file(req: FileListRequest) -> Dict[str, Any]:
    p = safe_path(req.path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return {"path": str(p), "content": p.read_text(encoding="utf-8", errors="ignore")}


@app.post("/api/tools/files/list")
async def list_files(req: FileListRequest) -> Dict[str, Any]:
    p = safe_path(req.path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    entries = [{"name": x.name, "is_dir": x.is_dir()} for x in sorted(p.iterdir())]
    return {"path": str(p), "entries": entries}


@app.websocket("/ws/{task_id}")
async def ws_task(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
    SOCKETS.setdefault(task_id, []).append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        SOCKETS[task_id].remove(websocket)


APP_HTML = """
<!doctype html><html><head><meta charset='utf-8'/><title>Local Agentic Pro</title></head>
<body style='font-family:Arial;max-width:1100px;margin:0 auto;padding:16px'>
<h1>Local Agentic AI - Professional MVP</h1>
<div style='display:grid;grid-template-columns:1fr 1fr;gap:16px'>
<section><h3>Task Runner</h3>
<textarea id='prompt' rows='4' style='width:100%'>Create README and notes.txt files.</textarea>
<textarea id='workflow' rows='10' style='width:100%'>{"nodes":[{"id":"planner","name":"Planner","role_prompt":"Plan","enabled_tools":[]},{"id":"executor","name":"Executor","role_prompt":"Execute","enabled_tools":["filesystem"]}],"edges":[]}</textarea>
<button onclick='runTask()'>Run Task</button><pre id='trace' style='background:#111;color:#0f0;min-height:180px;padding:8px'></pre></section>
<section><h3>Settings + Models</h3><button onclick='loadSettings()'>Load Settings</button><button onclick='saveSettings()'>Save Settings</button><button onclick='loadModels()'>Load Ollama Models</button>
<pre id='settings' style='background:#f4f4f4;padding:8px;min-height:160px'></pre>
<pre id='models' style='background:#eef;padding:8px;min-height:120px'></pre></section></div>
<h3>File Tool (create/read/list any extension inside sandbox)</h3>
<input id='filePath' style='width:300px' value='docs/example.md'/> <button onclick='createFile()'>Create/Write File</button> <button onclick='readFile()'>Read File</button>
<textarea id='fileContent' rows='5' style='width:100%'># Example\nThis file was created by the tool API.</textarea>
<button onclick='listFiles()'>List Sandbox Root</button>
<pre id='fileOut' style='background:#f7f7f7;padding:8px;min-height:120px'></pre>
<script>
const j=(x)=>JSON.stringify(x,null,2);const log=(x)=>document.getElementById('trace').textContent+=x+'\\n';
async function runTask(){document.getElementById('trace').textContent='';const prompt=document.getElementById('prompt').value;const workflow=JSON.parse(document.getElementById('workflow').value);const r=await fetch('/api/task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,workflow})});const d=await r.json();log('Task '+d.task_id);const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/'+d.task_id);ws.onopen=()=>ws.send('sub');ws.onmessage=(e)=>log(e.data);}
async function loadSettings(){const r=await fetch('/api/settings');document.getElementById('settings').textContent=j(await r.json())}
async function saveSettings(){const body=JSON.parse(document.getElementById('settings').textContent);const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});document.getElementById('settings').textContent=j(await r.json())}
async function loadModels(){const r=await fetch('/api/models');document.getElementById('models').textContent=j(await r.json())}
async function createFile(){const path=document.getElementById('filePath').value;const content=document.getElementById('fileContent').value;const r=await fetch('/api/tools/files/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,content})});document.getElementById('fileOut').textContent=j(await r.json())}
async function readFile(){const path=document.getElementById('filePath').value;const r=await fetch('/api/tools/files/read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});document.getElementById('fileOut').textContent=j(await r.json())}
async function listFiles(){const r=await fetch('/api/tools/files/list',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:'.'})});document.getElementById('fileOut').textContent=j(await r.json())}
loadSettings();loadModels();
</script></body></html>
"""
