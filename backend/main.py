from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import asyncio
import uuid
import time

app = FastAPI(title="Local Agentic AI MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ServiceSettings(BaseModel):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b-q4_0"
    embedding_model: str = "nomic-embed-text"
    redis_url: str = "redis://localhost:6379/0"
    searxng_url: str = "http://localhost:8080"
    allow_http_tool: bool = True
    http_allowlist: List[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])

class AgentSettings(BaseModel):
    planner_temperature: float = 0.3
    researcher_temperature: float = 0.7
    executor_temperature: float = 0.2
    critic_temperature: float = 0.2
    max_loop_count: int = 2
    max_steps: int = 8

class RuntimeSettings(BaseModel):
    sandbox_root: str = "/sandbox"
    code_exec_timeout_seconds: int = 30
    websocket_heartbeat_seconds: int = 15
    stream_chunk_delay_ms: int = 80

class AppSettings(BaseModel):
    services: ServiceSettings = ServiceSettings()
    agents: AgentSettings = AgentSettings()
    runtime: RuntimeSettings = RuntimeSettings()

class AgentNode(BaseModel):
    id: str
    name: str
    role_prompt: str
    enabled_tools: List[str] = Field(default_factory=list)

class WorkflowEdge(BaseModel):
    source: str
    target: str

class Workflow(BaseModel):
    nodes: List[AgentNode]
    edges: List[WorkflowEdge]

class TaskRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    workflow: Workflow

SETTINGS = AppSettings()
TASKS: Dict[str, Dict[str, Any]] = {}
SOCKETS: Dict[str, List[WebSocket]] = {}


async def emit(task_id: str, event: Dict[str, Any]) -> None:
    for ws in SOCKETS.get(task_id, []):
        await ws.send_json(event)


def ordered_nodes(workflow: Workflow) -> List[AgentNode]:
    # MVP: linearize by provided order. UI allows full customization/editing.
    return workflow.nodes


async def simulate_agent(node: AgentNode, prompt: str) -> str:
    await asyncio.sleep(SETTINGS.runtime.stream_chunk_delay_ms / 1000)
    return f"[{node.name}] processed: {prompt[:120]}"


async def run_task(task_id: str, request: TaskRequest) -> None:
    TASKS[task_id]["status"] = "running"
    start = time.time()
    results = []
    for index, node in enumerate(ordered_nodes(request.workflow), start=1):
        await emit(task_id, {"type": "agent_started", "step": index, "agent": node.name})
        out = await simulate_agent(node, request.prompt)
        results.append({"agent": node.name, "output": out})
        await emit(task_id, {"type": "agent_output", "step": index, "agent": node.name, "output": out})

    final = "\n".join([f"{r['agent']}: {r['output']}" for r in results])
    TASKS[task_id]["status"] = "done"
    TASKS[task_id]["result"] = final
    TASKS[task_id]["trace"] = results
    TASKS[task_id]["duration_seconds"] = round(time.time() - start, 2)
    await emit(task_id, {"type": "final_output", "output": final})




APP_HTML = """
<!doctype html>
<html>
<head><meta charset="utf-8"/><title>Local Agentic AI MVP</title></head>
<body style="font-family:Arial;padding:16px;max-width:1000px;margin:auto">
<h1>Local Agentic AI MVP (Single-Server UI)</h1>
<p>This UI is served directly by FastAPI so it works without npm/vite.</p>
<textarea id="prompt" rows="5" style="width:100%" placeholder="Ask your agents..."></textarea>
<button onclick="runTask()">Run Task</button>
<h3>Workflow JSON</h3>
<textarea id="workflow" rows="10" style="width:100%">{
  "nodes": [
    {"id":"planner","name":"Planner","role_prompt":"Decompose tasks","enabled_tools":[]},
    {"id":"researcher","name":"Researcher","role_prompt":"Gather context","enabled_tools":["web_search"]},
    {"id":"executor","name":"Executor","role_prompt":"Execute actions","enabled_tools":["filesystem","code_executor"]},
    {"id":"critic","name":"Critic","role_prompt":"Review outputs","enabled_tools":[]}
  ],
  "edges": []
}</textarea>
<h3>Settings</h3>
<button onclick="loadSettings()">Reload Settings</button>
<button onclick="saveSettings()">Save Settings</button>
<pre id="settings" style="background:#f4f4f4;padding:8px"></pre>
<h3>Live Trace</h3>
<pre id="trace" style="background:#111;color:#0f0;padding:8px;min-height:180px"></pre>
<script>
const api='';
let settingsObj=null;
async function loadSettings(){const r=await fetch(api+'/api/settings');settingsObj=await r.json();document.getElementById('settings').textContent=JSON.stringify(settingsObj,null,2);}
async function saveSettings(){try{settingsObj=JSON.parse(document.getElementById('settings').textContent);await fetch(api+'/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(settingsObj)});alert('Settings saved');}catch(e){alert('Invalid settings JSON: '+e.message)}}
function log(x){const t=document.getElementById('trace');t.textContent += x+'\n';}
async function runTask(){document.getElementById('trace').textContent='';const prompt=document.getElementById('prompt').value;const workflow=JSON.parse(document.getElementById('workflow').value);const r=await fetch(api+'/api/task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,workflow})});const d=await r.json();log('Task ID: '+d.task_id);const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/'+d.task_id);ws.onopen=()=>ws.send('subscribe');ws.onmessage=(e)=>log(e.data);}
loadSettings();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def app_home() -> HTMLResponse:
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


@app.post("/api/task")
async def create_task(request: TaskRequest) -> Dict[str, str]:
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"id": task_id, "status": "queued", "result": None, "trace": []}
    asyncio.create_task(run_task(task_id, request))
    return {"task_id": task_id}


@app.get("/api/task/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    return TASKS.get(task_id, {"error": "task not found"})


@app.get("/api/tasks")
async def list_tasks() -> List[Dict[str, Any]]:
    return list(TASKS.values())


@app.websocket("/ws/{task_id}")
async def task_ws(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
    SOCKETS.setdefault(task_id, []).append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        SOCKETS[task_id].remove(websocket)
