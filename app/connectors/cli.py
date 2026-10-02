import asyncio, os
from app.config import settings
from app.connectors.base import Connector

class CliConnector(Connector):
    async def invoke(self, tool, args):
        if not tool.command:
            raise ValueError("missing command")
        allowed = {x.strip() for x in settings.cli_allowlist.split(",") if x.strip()}
        executable = os.path.basename(tool.command[0])
        if executable not in allowed:
            raise PermissionError(f"executable {executable} not allowlisted")
        # No shell=True: arguments never pass through a shell parser.
        proc = await asyncio.create_subprocess_exec(
            *tool.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": os.environ.get("PATH","")}
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=settings.request_timeout_seconds)
        if proc.returncode != 0:
            raise RuntimeError(err.decode(errors="replace")[:10000])
        return {"stdout": out.decode(errors="replace")[:100000], "returncode": proc.returncode}
