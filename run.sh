#!/bin/bash
# run.sh — one-command entry for the local-agent starter.
# 1. Assumes Ollama is already running (ollama serve) with a qwen3 model pulled.
# 2. Waits for the qwen3 model to be listed.
# 3. Runs the agent loop (live mode), then the verifier.
# Exit code: the agent's, if it failed; otherwise the verifier's.
set -u
D="$(cd "$(dirname "$0")" && pwd)"

# Start Ollama first (ollama serve) with a qwen3 model pulled.

echo "waiting for Ollama to list qwen3..."
for i in $(seq 1 30); do
  if curl -s -m 5 http://127.0.0.1:11434/api/tags | grep -q qwen3; then
    echo "Ollama up, qwen3 present"
    break
  fi
  sleep 2
  if [ "$i" = "30" ]; then echo "Ollama did not come up in 60 s"; exit 2; fi
done

free -m 2>/dev/null | head -2
python3 "$D/agent.py" "$@"
AGENT_RC=$?
if [ "$AGENT_RC" -ne 0 ]; then
  echo "agent exited $AGENT_RC; skipping verify"
  exit "$AGENT_RC"
fi
python3 "$D/verify.py"
exit $?
