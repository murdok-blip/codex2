import React, { useEffect, useState } from 'react'

const API = 'http://localhost:8000'

export function App() {
  const [prompt, setPrompt] = useState('')
  const [taskId, setTaskId] = useState('')
  const [events, setEvents] = useState<any[]>([])
  const [settings, setSettings] = useState<any>(null)
  const [workflow, setWorkflow] = useState([
    { id: 'planner', name: 'Planner', role_prompt: 'Decompose tasks', enabled_tools: [] },
    { id: 'researcher', name: 'Researcher', role_prompt: 'Gather context', enabled_tools: ['web_search'] },
    { id: 'executor', name: 'Executor', role_prompt: 'Execute actions', enabled_tools: ['filesystem', 'code_executor'] },
    { id: 'critic', name: 'Critic', role_prompt: 'Review outputs', enabled_tools: [] }
  ])

  useEffect(() => { fetch(`${API}/api/settings`).then(r => r.json()).then(setSettings) }, [])

  useEffect(() => {
    if (!taskId) return
    const ws = new WebSocket(`ws://localhost:8000/ws/${taskId}`)
    ws.onopen = () => ws.send('subscribe')
    ws.onmessage = (e) => setEvents((prev) => [...prev, JSON.parse(e.data)])
    return () => ws.close()
  }, [taskId])

  async function runTask() {
    setEvents([])
    const payload = { prompt, workflow: { nodes: workflow, edges: [] } }
    const res = await fetch(`${API}/api/task`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    const data = await res.json()
    setTaskId(data.task_id)
  }

  async function saveSettings() {
    await fetch(`${API}/api/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) })
    alert('Settings saved')
  }

  return <div style={{ fontFamily: 'sans-serif', padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
    <section>
      <h2>Prompt + Workflow Builder (MVP)</h2>
      <textarea rows={6} value={prompt} onChange={e => setPrompt(e.target.value)} style={{ width: '100%' }} placeholder='Ask your agents to perform actions...' />
      <h3>Agents (fully editable)</h3>
      {workflow.map((agent, idx) => (
        <div key={agent.id} style={{ border: '1px solid #ddd', padding: 8, marginBottom: 8 }}>
          <input value={agent.name} onChange={e => {
            const next = [...workflow]; next[idx].name = e.target.value; setWorkflow(next)
          }} />
          <input value={agent.role_prompt} onChange={e => {
            const next = [...workflow]; next[idx].role_prompt = e.target.value; setWorkflow(next)
          }} style={{ width: '100%' }} />
          <input value={agent.enabled_tools.join(',')} onChange={e => {
            const next = [...workflow]; next[idx].enabled_tools = e.target.value.split(',').map(s => s.trim()).filter(Boolean); setWorkflow(next)
          }} style={{ width: '100%' }} placeholder='tools comma separated' />
        </div>
      ))}
      <button onClick={runTask}>Run Task</button>
      <p>Task: {taskId || '-'}</p>
      <h3>Live Trace</h3>
      <pre>{events.map((e, i) => <div key={i}>{JSON.stringify(e)}</div>)}</pre>
    </section>

    <section>
      <h2>Solid Settings Section</h2>
      {settings && <>
        <label>Ollama Base URL <input value={settings.services.ollama_base_url} onChange={e => setSettings({ ...settings, services: { ...settings.services, ollama_base_url: e.target.value } })} /></label><br />
        <label>Ollama Model <input value={settings.services.ollama_model} onChange={e => setSettings({ ...settings, services: { ...settings.services, ollama_model: e.target.value } })} /></label><br />
        <label>Embedding Model <input value={settings.services.embedding_model} onChange={e => setSettings({ ...settings, services: { ...settings.services, embedding_model: e.target.value } })} /></label><br />
        <label>Redis URL <input value={settings.services.redis_url} onChange={e => setSettings({ ...settings, services: { ...settings.services, redis_url: e.target.value } })} /></label><br />
        <label>SearXNG URL <input value={settings.services.searxng_url} onChange={e => setSettings({ ...settings, services: { ...settings.services, searxng_url: e.target.value } })} /></label><br />
        <label>Planner Temp <input type='number' step='0.1' value={settings.agents.planner_temperature} onChange={e => setSettings({ ...settings, agents: { ...settings.agents, planner_temperature: Number(e.target.value) } })} /></label><br />
        <label>Researcher Temp <input type='number' step='0.1' value={settings.agents.researcher_temperature} onChange={e => setSettings({ ...settings, agents: { ...settings.agents, researcher_temperature: Number(e.target.value) } })} /></label><br />
        <label>Executor Temp <input type='number' step='0.1' value={settings.agents.executor_temperature} onChange={e => setSettings({ ...settings, agents: { ...settings.agents, executor_temperature: Number(e.target.value) } })} /></label><br />
        <label>Critic Temp <input type='number' step='0.1' value={settings.agents.critic_temperature} onChange={e => setSettings({ ...settings, agents: { ...settings.agents, critic_temperature: Number(e.target.value) } })} /></label><br />
        <label>Max Steps <input type='number' value={settings.agents.max_steps} onChange={e => setSettings({ ...settings, agents: { ...settings.agents, max_steps: Number(e.target.value) } })} /></label><br />
        <label>Sandbox Root <input value={settings.runtime.sandbox_root} onChange={e => setSettings({ ...settings, runtime: { ...settings.runtime, sandbox_root: e.target.value } })} /></label><br />
        <label>Code Timeout <input type='number' value={settings.runtime.code_exec_timeout_seconds} onChange={e => setSettings({ ...settings, runtime: { ...settings.runtime, code_exec_timeout_seconds: Number(e.target.value) } })} /></label><br />
        <button onClick={saveSettings}>Save Settings</button>
      </>}
    </section>
  </div>
}
