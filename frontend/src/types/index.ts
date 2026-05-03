export type AgentNode = { id: string; name: string; role_prompt: string; enabled_tools: string[] }
export type Workflow = { nodes: AgentNode[]; edges: { source: string; target: string }[] }
