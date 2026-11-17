"""Verify Epic's UE 5.9 MCP server and the loaded warehouse map without edits."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class UnrealMCP:
    def __init__(self, url, timeout=60):
        self.url = url
        self.timeout = timeout
        self.sequence = 0
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    def request(self, method, params=None, notification=False):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            self.sequence += 1
            payload["id"] = self.sequence
        request = Request(self.url, json.dumps(payload).encode("utf-8"), self.headers)
        with urlopen(request, timeout=self.timeout) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                self.headers["Mcp-Session-Id"] = session
            raw = response.read().decode("utf-8")
        if not raw:
            if notification:
                return None
            raise RuntimeError(f"Empty response to {method}")
        if raw.lstrip().startswith("{"):
            result = json.loads(raw)
        else:
            messages = [json.loads(line[5:].strip()) for line in raw.splitlines()
                        if line.startswith("data:") and line[5:].strip()]
            result = next((item for item in messages if item.get("id") == payload.get("id")), None)
            if result is None:
                raise RuntimeError(f"No matching response to {method}")
        if "error" in result:
            raise RuntimeError(json.dumps(result["error"], ensure_ascii=False))
        return result["result"]

    def tool(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        return result

    def close(self):
        if "Mcp-Session-Id" not in self.headers:
            return
        try:
            with urlopen(Request(self.url, headers=self.headers, method="DELETE"),
                         timeout=self.timeout):
                pass
        except HTTPError as error:
            if error.code not in (404, 405):
                raise


def decoded(result):
    if "structuredContent" in result:
        return result["structuredContent"]
    texts = [item["text"] for item in result.get("content", []) if item["type"] == "text"]
    return json.loads("\n".join(texts))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--project", type=Path, default=project / "Test.uproject")
    parser.add_argument("--map", default="/Game/Maps/GHS_GlobalWarehouse")
    parser.add_argument("--out", type=Path, default=project / "Saved/UE59Web/mcp-verification.json")
    args = parser.parse_args()
    project_file = args.project.resolve()
    if not args.map.startswith("/Game/"):
        parser.error("--map must be a /Game/ package path")
    map_file = project_file.parent / "Content" / (args.map.removeprefix("/Game/") + ".umap")
    tracked = [project_file, map_file]
    before = {str(path): digest(path) for path in tracked}
    report = {"verifiedAtUtc": datetime.now(timezone.utc).isoformat(), "url": args.url,
              "readOnly": True, "pass": False}
    client = UnrealMCP(args.url)
    try:
        initialization = client.request("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "ghs-ue59-readonly-verifier", "version": "1.0"},
        })
        report["initialize"] = initialization
        client.headers["MCP-Protocol-Version"] = initialization["protocolVersion"]
        client.request("notifications/initialized", notification=True)
        info = initialization["serverInfo"]
        instance = initialization["_meta"]["com.epicgames.unrealengine/instance"]
        if info["name"] != "unreal-mcp" or not info["version"].startswith("5.9."):
            raise RuntimeError("Endpoint is not Epic's UE 5.9 MCP server")
        if Path(instance["projectFile"]).resolve() != project_file:
            raise RuntimeError("MCP server belongs to a different project")
        report["tools"] = client.request("tools/list", {})
        report["toolsets"] = client.tool("list_toolsets", {})
        toolset = "EditorToolset.LevelToolset"
        names = [f"{toolset}.GetCurrentLevel", f"{toolset}.FindActors"]
        report["schemas"] = client.tool("describe_tools", {"tool_names": names})
        descriptors = decoded(report["schemas"])["tools"]
        for name in names:
            if not descriptors[name].get("annotations", {}).get("readOnlyHint"):
                raise RuntimeError(f"Tool does not advertise read-only access: {name}")
        level = decoded(client.tool("call_tool", {
            "toolset_name": toolset, "tool_name": "GetCurrentLevel", "arguments": {},
        }))["returnValue"]
        actors = decoded(client.tool("call_tool", {
            "toolset_name": toolset, "tool_name": "FindActors", "arguments": {},
        }))["returnValue"]
        report.update(currentLevel=level, actorCount=len(actors), actors=actors)
        if level != args.map or not actors:
            raise RuntimeError("Expected warehouse map and nonempty actor list were not returned")
        after = {str(path): digest(path) for path in tracked}
        report.update(filesBefore=before, filesAfter=after, filesUnchanged=before == after)
        if before != after:
            raise RuntimeError("Project or map changed during verification")
        report["pass"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        try:
            client.close()
        except Exception as error:
            report["sessionCleanupWarning"] = str(error)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in
                      ("pass", "currentLevel", "actorCount", "filesUnchanged", "error")},
                     ensure_ascii=False))
    print(f"Evidence: {args.out.resolve()}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
