# Deep Agents CLI middleware flow 
 
## Purpose 
 
This document summarizes the middleware execution flow for the Deep Agents CLI, from CLI assembly in `deepagents_cli.agent.create_cli_agent()` through SDK assembly in `deepagents.create_deep_agent()`, and then into a concrete state transition example where a tool call is followed by summarization.
