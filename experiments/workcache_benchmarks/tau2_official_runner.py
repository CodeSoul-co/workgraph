#!/usr/bin/env python3
"""Run one tau2 task through the upstream tau2 runner and evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path) -> None:
  if not path.exists():
    return
  for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def normalize_tau2_model(model: str) -> str:
  if "/" in model:
    return model
  if model.startswith("deepseek"):
    return f"deepseek/{model}"
  return model


def stable_hash(value: Any) -> str:
  return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def configure_provider_env() -> None:
  deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
  deepseek_base = os.environ.get("DEEPSEEK_BASE_URL")
  if deepseek_key:
    os.environ.setdefault("OPENAI_API_KEY", deepseek_key)
  if deepseek_base:
    os.environ.setdefault("OPENAI_BASE_URL", deepseek_base)
    os.environ.setdefault("OPENAI_API_BASE", deepseek_base)


def run_hypha_bridge(args: argparse.Namespace, operations: list[dict[str, Any]]) -> dict[str, Any]:
  payload = {
    "hyphaRoot": str(args.hypha_root),
    "storeKind": "sqlite",
    "sqlitePath": str(args.workcache_sqlite),
    "policy": json.loads(args.workcache_policy_json),
    "operations": operations,
  }
  result = subprocess.run(
    ["node", str(args.workcache_bridge)],
    input=json.dumps(payload, ensure_ascii=False),
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(ROOT),
    check=False,
  )
  if result.returncode != 0:
    raise RuntimeError(f"Hypha WorkCache bridge failed: {result.stderr.strip()}")
  return json.loads(result.stdout)


def message_to_dict(message: Any) -> dict[str, Any]:
  dumped = message.model_dump(mode="json")
  return {
    "role": dumped.get("role"),
    "content": dumped.get("content"),
    "tool_calls": dumped.get("tool_calls"),
    "requestor": dumped.get("requestor"),
    "error": dumped.get("error"),
    "turn_idx": dumped.get("turn_idx"),
    "timestamp": dumped.get("timestamp"),
    "cost": dumped.get("cost"),
    "usage": dumped.get("usage"),
    "generation_time_seconds": dumped.get("generation_time_seconds"),
  }


def install_workcache_generate(args: argparse.Namespace, source_events: list[dict[str, Any]]) -> None:
  if not args.workcache_policy_json or not args.workcache_sqlite:
    return
  policy = json.loads(args.workcache_policy_json)
  if not policy.get("enabled") or not policy.get("trees", {}).get("ComputationTree", {}).get("enabled"):
    return

  import tau2.agent.llm_agent as llm_agent_module
  import tau2.utils.llm_utils as llm_utils
  from tau2.data_model.message import AssistantMessage, ToolCall
  from tau2.config import DEFAULT_MAX_RETRIES

  original_generate = llm_utils.generate
  call_index = {"value": 0}

  def make_identity(model: str, request_data: dict[str, Any]) -> dict[str, Any]:
    return {
      "sourceEventType": "model.call.completed",
      "provider": "deepseek" if model.startswith("deepseek/") else model.split("/", 1)[0],
      "model": model,
      "requestHash": stable_hash(request_data),
      "paramsHash": stable_hash(request_data.get("kwargs", {})),
      "environmentHash": stable_hash({"provider": "deepseek", "base_url": os.environ.get("DEEPSEEK_BASE_URL")}),
    }

  def make_event(model: str, request_data: dict[str, Any], message: AssistantMessage, *, cache_reuse: bool) -> dict[str, Any]:
    call_index["value"] += 1
    identity = make_identity(model, request_data)
    event = {
      "id": f"{args.workcache_run_id}:model.call.completed:tau2:{call_index['value']}",
      "type": "model.call.completed",
      "runId": args.workcache_run_id,
      "sessionId": f"workgraph:{args.cache_scope}",
      "stepId": request_data.get("call_name") or "tau2_llm_call",
      "agentId": "agent.tau2-bench.deepseek_pro",
      "timestamp": message.timestamp,
      "payload": {
        "provider": identity["provider"],
        "model": identity["model"],
        "requestHash": identity["requestHash"],
        "paramsHash": identity["paramsHash"],
        "envHash": identity["environmentHash"],
        "output": {
          "content": message.content or "",
          "toolCalls": [tool_call.model_dump(mode="json") for tool_call in message.tool_calls] if message.tool_calls else None,
          "rawResponseHash": stable_hash(message.raw_data),
        },
        "usage": message.usage or {},
        "finishReason": (message.raw_data or {}).get("choices", [{}])[0].get("finish_reason"),
        "latencyMs": (message.generation_time_seconds or 0) * 1000,
        "cacheReuse": cache_reuse,
        "validity": {
          "status": "valid",
          "sourceHashes": {
            "request": identity["requestHash"],
            "params": identity["paramsHash"],
            "environment": identity["environmentHash"],
          },
        },
      },
    }
    source_events.append(event)
    return event

  def cached_message(lookup: dict[str, Any]) -> AssistantMessage | None:
    block = lookup.get("block") or {}
    value = block.get("value") or {}
    output = value.get("output") or {}
    tool_calls = output.get("toolCalls") or []
    return AssistantMessage(
      role="assistant",
      content=output.get("content") or "",
      tool_calls=[
        ToolCall(
          id=tool_call.get("id", ""),
          name=tool_call.get("name", ""),
          arguments=tool_call.get("arguments") or {},
        )
        for tool_call in tool_calls
      ]
      or None,
      cost=0.0,
      usage={"prompt_tokens": 0, "completion_tokens": 0},
      raw_data={
        "cached_from_workcache": True,
        "block_id": block.get("id"),
        "source_event_id": block.get("sourceEventId"),
      },
      generation_time_seconds=0.0,
    )

  def generate_with_workcache(model: str, messages: list[Any], tools: list[Any] | None = None, tool_choice: str | None = None, call_name: str | None = None, **kwargs: Any) -> AssistantMessage:
    if kwargs.get("num_retries") is None:
      kwargs["num_retries"] = DEFAULT_MAX_RETRIES
    litellm_messages = llm_utils.to_litellm_messages(messages)
    tools_schema = [tool.openai_schema for tool in tools] if tools else None
    if tools_schema and tool_choice is None:
      tool_choice = "auto"
    request_data = {
      "model": model,
      "messages": litellm_messages,
      "tools": tools_schema,
      "tool_choice": tool_choice,
      "kwargs": kwargs,
      "call_name": call_name,
    }
    identity = make_identity(model, request_data)
    lookup = run_hypha_bridge(
      args,
      [
        {
          "op": "lookup",
          "query": {
            "treeType": "ComputationTree",
            "nodeType": "computation",
            "identity": identity,
          },
        }
      ],
    )["results"][0]["lookup"]
    if lookup.get("hit"):
      message = cached_message(lookup)
      if message and (message.has_content() or message.is_tool_call()):
        event = make_event(model, request_data, message, cache_reuse=True)
        run_hypha_bridge(args, [{"op": "ingest", "events": [event]}])
        return message

    message = original_generate(
      model=model,
      messages=messages,
      tools=tools,
      tool_choice=tool_choice,
      call_name=call_name,
      **kwargs,
    )
    event = make_event(model, request_data, message, cache_reuse=False)
    run_hypha_bridge(args, [{"op": "ingest", "events": [event]}])
    return message

  llm_utils.generate = generate_with_workcache
  llm_agent_module.generate = generate_with_workcache


def register_non_empty_user() -> None:
  from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage, UserMessage
  from tau2.registry import registry
  from tau2.user.user_simulator import UserSimulator
  from tau2.utils.llm_utils import generate

  class NonEmptyUserSimulator(UserSimulator):
    def _assistant_to_user(self, assistant_message: AssistantMessage) -> UserMessage:
      user_message = UserMessage(
        role="user",
        content=assistant_message.content,
        cost=assistant_message.cost,
        usage=assistant_message.usage,
        raw_data=assistant_message.raw_data,
      )
      if assistant_message.tool_calls is not None:
        user_message.tool_calls = [
          ToolCall(
            id=tool_call.id,
            name=tool_call.name,
            arguments=tool_call.arguments,
            requestor="user",
          )
          for tool_call in assistant_message.tool_calls
        ]
      return user_message

    def _prepare_state(self, message: Any, state: Any) -> None:
      if isinstance(message, MultiToolMessage):
        state.messages.extend(message.tool_messages)
      elif isinstance(message, ToolMessage):
        state.messages.append(message)
      elif message.has_content() or message.is_tool_call():
        state.messages.append(message)

    def _generate_from_state(self, state: Any, *, retry_hint: str | None = None) -> UserMessage:
      messages = state.system_messages + state.flip_roles()
      if retry_hint is not None:
        messages.append(UserMessage(role="user", content=retry_hint))
      assistant_message = generate(
        model=self.llm,
        messages=messages,
        tools=self.tools,
        call_name="user_simulator_response",
        **self.llm_args,
      )
      return self._assistant_to_user(assistant_message)

    def _generate_next_message(self, message: Any, state: Any) -> UserMessage:
      self._prepare_state(message, state)
      user_message = self._generate_from_state(state)
      if user_message.has_content() or user_message.is_tool_call():
        return user_message

      retry_hint = (
        "The previous simulator response was empty. Respond as the customer with "
        "a non-empty utterance or a valid customer-side tool call. Do not answer "
        "as the support agent."
      )
      for _ in range(2):
        user_message = self._generate_from_state(state, retry_hint=retry_hint)
        if user_message.has_content() or user_message.is_tool_call():
          user_message.raw_data = {
            **(user_message.raw_data or {}),
            "workgraph_retry_reason": "empty_user_simulator_response",
          }
          return user_message
      return user_message

  registry.register_user(NonEmptyUserSimulator, "workgraph_non_empty_user_simulator")


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", required=True)
  parser.add_argument("--task-id", required=True)
  parser.add_argument("--model", required=True)
  parser.add_argument("--output", type=Path, required=True)
  parser.add_argument("--seed", type=int, default=300)
  parser.add_argument("--max-steps", type=int, default=200)
  parser.add_argument("--timeout", type=float, default=None)
  parser.add_argument("--save-dir", type=Path, default=None)
  parser.add_argument("--hypha-root", type=Path, default=ROOT / "hypha")
  parser.add_argument("--workcache-bridge", type=Path, default=ROOT / "experiments" / "workcache_benchmarks" / "hypha_workcache_bridge.js")
  parser.add_argument("--workcache-sqlite", type=Path, default=None)
  parser.add_argument("--workcache-policy-json", default="")
  parser.add_argument("--workcache-run-id", default="")
  parser.add_argument("--cache-scope", default="")
  args = parser.parse_args()

  load_dotenv(ROOT / ".env")
  configure_provider_env()
  workcache_source_events: list[dict[str, Any]] = []
  install_workcache_generate(args, workcache_source_events)
  register_non_empty_user()

  from tau2.data_model.simulation import TextRunConfig
  from tau2.runner import get_tasks, run_single_task

  task_id = args.task_id.split(":", 1)[1] if ":" in args.task_id else args.task_id
  tasks = get_tasks(args.domain, task_ids=[task_id])
  config = TextRunConfig(
    domain=args.domain,
    agent="llm_agent",
    user="workgraph_non_empty_user_simulator",
    llm_agent=normalize_tau2_model(args.model),
    llm_user=normalize_tau2_model(args.model),
    llm_args_agent={"temperature": 0.0},
    llm_args_user={"temperature": 0.0},
    max_steps=args.max_steps,
    timeout=args.timeout,
    enforce_communication_protocol=True,
  )
  simulation = run_single_task(
    config,
    tasks[0],
    seed=args.seed,
    save_dir=args.save_dir,
    verbose_logs=args.save_dir is not None,
  )
  messages = [message_to_dict(message) for message in simulation.get_messages()]
  llm_log_files: list[str] = []
  if args.save_dir is not None:
    llm_log_files = sorted(str(path) for path in args.save_dir.glob("artifacts/**/llm_debug/*.json"))
  reward_info = simulation.reward_info.model_dump(mode="json") if simulation.reward_info else None
  payload = {
    "ok": True,
    "domain": args.domain,
    "task_id": args.task_id,
    "official_task_id": task_id,
    "model": normalize_tau2_model(args.model),
    "simulation": {
      "id": simulation.id,
      "task_id": simulation.task_id,
      "duration": simulation.duration,
      "termination_reason": simulation.termination_reason,
      "agent_cost": simulation.agent_cost,
      "user_cost": simulation.user_cost,
      "reward_info": reward_info,
      "messages": messages,
      "seed": simulation.seed,
      "mode": simulation.mode,
      "llm_log_files": llm_log_files,
      "workcache_source_events": workcache_source_events,
    },
  }
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
  print(json.dumps({"ok": True, "output": str(args.output), "reward": reward_info.get("reward") if reward_info else None}))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
