import { expect, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { runBlender } from "./blender-process.ts";

const blender = process.env.BLENDER_EXECUTABLE ?? Bun.which("blender");
const root = resolve(import.meta.dir, "..");
const diagnostic = join(root, "skills/blender-asset-validation/scripts/diagnose_topology.py");

test.skipIf(!blender)("topology diagnostics localize evaluated degeneracies in transformed meshes and bound findings", async () => {
  const temporary = await mkdtemp(join(tmpdir(), "bas-topology-test-"));
  try {
    const fixture = join(temporary, "fixture.py");
    const assetPath = join(temporary, "fixture.blend");
    await writeFile(fixture, `import bpy\n\nbpy.ops.object.select_all(action='SELECT')\nbpy.ops.object.delete(use_global=False)\n\ndef mesh(name, vertices, faces, location, edges=[]):\n    data = bpy.data.meshes.new(name + 'Mesh')\n    data.from_pydata(vertices, edges, faces)\n    data.update()\n    obj = bpy.data.objects.new(name, data)\n    bpy.context.collection.objects.link(obj)\n    obj.location = location\n    return obj\n\nmesh('Healthy', [(0,0,0), (0,1,0), (0,0,1)], [(0,1,2)], (1,2,3))\nmesh('Degenerate', [(0,0,0), (1,0,0), (2,0,0)], [(0,1,2)], (10,20,30))\nmesh('ZeroEdge', [(0,0,0), (0,0,0)], [], (5,5,5), [(0,1)])\nbpy.ops.wm.save_as_mainfile(filepath=r'${assetPath.replaceAll("\\", "\\\\")}')\n`, "utf8");
    const built = await runBlender({ blenderPath: blender!, scriptPath: fixture, timeoutMs: 30_000 });
    expect(built.exitCode, built.stdout + built.stderr).toBe(0);

    const pagedPath = join(temporary, "paged.json");
    const paged = await runBlender({ blenderPath: blender!, scriptPath: diagnostic, scriptArgs: ["--input", assetPath, "--output", pagedPath, "--limit", "1"], timeoutMs: 30_000 });
    expect(paged.exitCode, paged.stdout + paged.stderr).toBe(0);
    const report = JSON.parse(await readFile(pagedPath, "utf8"));
    expect(report.counts).toMatchObject({ mesh_objects: 3, degenerate_faces: 1, zero_length_edges: 1 });
    expect(report.total_findings).toBe(2);
    expect(report.truncated).toBe(true);
    expect(report.findings).toEqual([expect.objectContaining({ objectName: "Degenerate", evaluatedElementIndex: 0, kind: "degenerate_face", worldCenter: [11, 20, 30], area: 0 })]);

    const healthyPath = join(temporary, "healthy.json");
    const healthy = await runBlender({ blenderPath: blender!, scriptPath: diagnostic, scriptArgs: ["--input", assetPath, "--output", healthyPath, "--object", "Healthy", "--limit", "1"], timeoutMs: 30_000 });
    expect(healthy.exitCode, healthy.stdout + healthy.stderr).toBe(0);
    expect(JSON.parse(await readFile(healthyPath, "utf8"))).toMatchObject({ scope: { objectName: "Healthy" }, total_findings: 0, findings: [] });

    const missing = await runBlender({ blenderPath: blender!, scriptPath: diagnostic, scriptArgs: ["--input", assetPath, "--output", join(temporary, "missing.json"), "--object", "Not an object"], timeoutMs: 30_000 });
    expect(missing.exitCode).not.toBe(0);
    expect(missing.stdout + missing.stderr).toContain("Exact object not found: Not an object");
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}, 90_000);
