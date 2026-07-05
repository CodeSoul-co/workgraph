#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function graphToJson(graph) {
  if (!graph) return null;
  return {
    ...graph,
    nodes: Array.from(graph.nodes.values()),
    edges: Array.from(graph.edges.values()),
  };
}

async function main() {
  const payload = JSON.parse(await readStdin());
  const hyphaRoot =
    payload.hyphaRoot ||
    process.env.HYPHA_ROOT ||
    path.resolve(__dirname, '..', '..', 'hypha');
  const workcache = require(path.join(hyphaRoot, 'packages', 'workcache', 'dist'));
  const {
    MemoryWorkCacheStore,
    SQLiteWorkCacheStore,
    WorkCacheManager,
    createWorkCacheKey,
    hashStableJson,
  } = workcache;

  const storeKind = payload.storeKind || (payload.sqlitePath ? 'sqlite' : 'memory');
  let store;
  if (storeKind === 'sqlite') {
    fs.mkdirSync(path.dirname(payload.sqlitePath), { recursive: true });
    store = new SQLiteWorkCacheStore({ filename: payload.sqlitePath });
  } else {
    store = new MemoryWorkCacheStore();
  }

  const manager = new WorkCacheManager({
    store,
    hotIndex: payload.hotIndex !== false,
    policy: payload.policy,
  });

  const results = [];
  for (const operation of payload.operations || []) {
    if (operation.op === 'cacheKey') {
      results.push({
        op: operation.op,
        cacheKey: createWorkCacheKey(operation.input),
      });
      continue;
    }

    if (operation.op === 'hashStableJson') {
      results.push({
        op: operation.op,
        hash: hashStableJson(operation.input),
      });
      continue;
    }

    if (operation.op === 'lookup') {
      const cacheKey =
        operation.query.cacheKey ||
        createWorkCacheKey({
          treeType: operation.query.treeType,
          nodeType: operation.query.nodeType,
          identity: operation.query.identity,
        });
      const lookup = await manager.lookup({
        treeType: operation.query.treeType,
        cacheKey,
      });
      results.push({
        op: operation.op,
        cacheKey,
        lookup,
      });
      continue;
    }

    if (operation.op === 'ingest') {
      const auditEvents = [];
      for (const event of operation.events || []) {
        const derived = await manager.ingest(event);
        auditEvents.push(...derived);
      }
      results.push({
        op: operation.op,
        auditEvents,
      });
      continue;
    }

    if (operation.op === 'materializePromptPrefix') {
      const materialized = await manager.materializePromptPrefix(operation.sourceEvent);
      results.push({
        op: operation.op,
        materialized,
      });
      continue;
    }

    if (operation.op === 'snapshot') {
      const blocks = {};
      for (const treeType of operation.treeTypes || [
        'PlanTree',
        'ComputationTree',
        'ToolTree',
        'ObservationTree',
        'VerificationTree',
        'MemoryTree',
        'PromptPrefixTree',
      ]) {
        blocks[treeType] = await store.list(treeType);
      }
      const graphs = {};
      for (const runId of operation.runIds || []) {
        graphs[runId] = graphToJson(manager.getWorkGraph(runId));
      }
      results.push({
        op: operation.op,
        blocks,
        graphs,
        demandSignals: manager.listDemandSignals(),
      });
      continue;
    }

    throw new Error(`Unsupported bridge operation: ${operation.op}`);
  }

  process.stdout.write(JSON.stringify({ ok: true, results }, null, 2));
}

main().catch((error) => {
  process.stderr.write(`${error && error.stack ? error.stack : String(error)}\n`);
  process.exit(1);
});
