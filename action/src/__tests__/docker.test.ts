import { afterEach, describe, expect, mock, spyOn, test } from "bun:test"
import * as childProcess from "node:child_process"
import * as fs from "node:fs"
import * as os from "node:os"
import * as path from "node:path"
import {
  collectBuild,
  listImageIds,
  parseSize,
  readCacheHitRatio,
  readContainers,
  readImageSize,
  readLayers,
  scrubInstruction,
} from "../docker"

afterEach(() => {
  mock.restore()
})

/**
 * Stand in for the docker CLI, dispatching on the subcommand.
 *
 * Every probe in docker.ts shells out through the same helper, so routing on
 * `args[0]` is what lets one mock serve `docker images`, `docker history`,
 * `docker image inspect`, `docker ps` and `docker inspect` in a single test.
 * A subcommand with no entry throws, which is exactly how the real CLI behaves
 * on an unknown image and drives the null-returning paths.
 */
function mockDocker(responses: Record<string, string | Error>) {
  spyOn(childProcess, "execFileSync").mockImplementation(((
    _cmd: string,
    args: string[],
  ) => {
    const reply = responses[args[0]]
    if (reply === undefined || reply instanceof Error) {
      throw reply ?? new Error(`no mock for docker ${args[0]}`)
    }
    return reply
  }) as unknown as typeof childProcess.execFileSync)
}

describe("parseSize", () => {
  test("parses the human sizes docker history prints", () => {
    expect(parseSize("0B")).toBe(0)
    expect(parseSize("512B")).toBe(512)
    expect(parseSize("1.2GB")).toBe(1_200_000_000)
    expect(parseSize("45.7MB")).toBe(45_700_000)
    expect(parseSize("2 kB")).toBe(2000)
  })

  test("returns 0 rather than NaN for anything unrecognised", () => {
    // A size that fails to parse must not poison the summed layer total.
    expect(parseSize(undefined)).toBe(0)
    expect(parseSize("")).toBe(0)
    expect(parseSize("n/a")).toBe(0)
  })
})

describe("scrubInstruction", () => {
  test("keeps only the instruction keyword", () => {
    expect(scrubInstruction("/bin/sh -c #(nop)  USER app")).toBe("USER")
    expect(scrubInstruction("COPY dir:abc123 in /app")).toBe("COPY")
  })

  test("never lets a RUN command's arguments through", () => {
    // docker history reports the literal command, which routinely carries
    // build args and inline credentials. The text is discarded on the runner,
    // not redacted by pattern — a denylist would leak whatever it missed.
    const secretish =
      "/bin/sh -c npm config set //registry.npmjs.org/:_authToken=npm_A1b2C3d4E5"
    const result = scrubInstruction(secretish)
    expect(result).toBe("RUN")
    expect(result).not.toContain("npm_A1b2C3d4E5")
    expect(result).not.toContain("authToken")
  })

  test("falls back to RUN for a bare shell command", () => {
    expect(scrubInstruction("/bin/sh -c apt-get update")).toBe("RUN")
  })
})

describe("readCacheHitRatio", () => {
  function withMetadata(body: string, fn: (p: string) => void) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gsops-"))
    const file = path.join(dir, "metadata.json")
    fs.writeFileSync(file, body)
    try {
      fn(file)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  }

  test("computes the ratio of cached steps", () => {
    withMetadata(
      JSON.stringify({
        steps: [
          { cached: true },
          { cached: true },
          { cached: false },
          { cached: true },
        ],
      }),
      (file) => {
        expect(readCacheHitRatio(file)).toBe(0.75)
      },
    )
  })

  test("returns null, not 0, when metadata is missing", () => {
    // 0 would be indistinguishable from "every layer missed", which is the
    // exact condition image_layer_cache_ineffective fires on.
    expect(readCacheHitRatio("/nonexistent/metadata.json")).toBeNull()
  })

  test("returns null for metadata without steps", () => {
    withMetadata(JSON.stringify({ "image.name": "app:latest" }), (file) => {
      expect(readCacheHitRatio(file)).toBeNull()
    })
  })

  test("returns null for unparseable metadata", () => {
    withMetadata("{ not json", (file) => {
      expect(readCacheHitRatio(file)).toBeNull()
    })
  })
})

describe("listImageIds", () => {
  test("returns the ids docker images prints", () => {
    mockDocker({ images: "sha256:aaa\nsha256:bbb\n\n" })
    expect(listImageIds()).toEqual(["sha256:aaa", "sha256:bbb"])
  })

  test("returns an empty list when docker is unavailable", () => {
    // The pre step diffs this against the post step. Returning [] rather than
    // throwing is what keeps a runner without Docker from failing the build.
    mockDocker({})
    expect(listImageIds()).toEqual([])
  })
})

describe("readLayers", () => {
  test("parses size and instruction per layer", () => {
    mockDocker({
      history:
        "1.2GB\tCOPY dir:abc123 in /app\n0B\t/bin/sh -c #(nop)  USER app",
    })
    expect(readLayers("sha256:aaa")).toEqual([
      { index: 0, size_bytes: 1_200_000_000, instruction: "COPY" },
      { index: 1, size_bytes: 0, instruction: "USER" },
    ])
  })

  test("returns null when the image cannot be read", () => {
    mockDocker({})
    expect(readLayers("sha256:missing")).toBeNull()
  })
})

describe("readImageSize", () => {
  test("parses the size docker image inspect prints", () => {
    mockDocker({ image: "2400000000\n" })
    expect(readImageSize("sha256:aaa")).toBe(2_400_000_000)
  })

  test("returns null for unparseable output", () => {
    mockDocker({ image: "not-a-number" })
    expect(readImageSize("sha256:aaa")).toBeNull()
  })

  test("returns null when the image cannot be inspected", () => {
    mockDocker({})
    expect(readImageSize("sha256:missing")).toBeNull()
  })
})

describe("readContainers", () => {
  test("parses one row per container", () => {
    mockDocker({
      ps: "c1\n",
      inspect: "/api\ttrue\t2\thealthy\t536870912",
    })
    expect(readContainers()).toEqual([
      {
        name: "api",
        oom_killed: true,
        restart_count: 2,
        has_healthcheck: true,
        health_status: "healthy",
        mem_limit_bytes: 536_870_912,
        peak_rss_bytes: null,
        peak_pids: null,
        cpu_throttled_percent: null,
        exit_code: null,
        observed: false,
      },
    ])
  })

  test("merges what the daemon measured onto the inspected container", () => {
    mockDocker({ ps: "c1\n", inspect: "/api\tfalse\t0\thealthy\t536870912" })
    const [container] = readContainers({
      api: {
        name: "api",
        id: "c1",
        peak_rss_bytes: 90_000_000,
        peak_pids: 12,
        cpu_throttled_percent: 4.5,
        oom_killed: false,
        exit_code: 0,
        samples: 3,
      },
    }) ?? []
    expect(container.peak_rss_bytes).toBe(90_000_000)
    expect(container.cpu_throttled_percent).toBe(4.5)
    expect(container.mem_limit_bytes).toBe(536_870_912)
    expect(container.observed).toBe(true)
  })

  test("keeps a container the post step can no longer see", () => {
    // `docker compose down` removes containers before post runs. Dropping them
    // would silently exclude exactly the short-lived ones most likely to have
    // been OOM-killed.
    mockDocker({ ps: "" })
    const containers = readContainers({
      worker: {
        name: "worker",
        id: "c9",
        peak_rss_bytes: 700_000_000,
        peak_pids: 4,
        cpu_throttled_percent: null,
        oom_killed: true,
        exit_code: 137,
        samples: 2,
      },
    })
    expect(containers).toEqual([
      {
        name: "worker",
        oom_killed: true,
        restart_count: 0,
        has_healthcheck: false,
        health_status: "none",
        mem_limit_bytes: null,
        peak_rss_bytes: 700_000_000,
        peak_pids: 4,
        cpu_throttled_percent: null,
        exit_code: 137,
        observed: true,
      },
    ])
  })

  test("takes an OOM from the event stream when inspect missed it", () => {
    mockDocker({ ps: "c1\n", inspect: "/api\tfalse\t0\tnone\t268435456" })
    const [container] = readContainers({
      api: {
        name: "api",
        id: "c1",
        peak_rss_bytes: 268_000_000,
        peak_pids: null,
        cpu_throttled_percent: null,
        oom_killed: true,
        exit_code: null,
        samples: 1,
      },
    }) ?? []
    expect(container.oom_killed).toBe(true)
  })

  test("treats 'none' health as no healthcheck", () => {
    mockDocker({ ps: "c1\n", inspect: "/db\tfalse\t0\tnone\t0" })
    const [container] = readContainers() ?? []
    expect(container.has_healthcheck).toBe(false)
    expect(container.oom_killed).toBe(false)
    expect(container.mem_limit_bytes).toBe(0)
  })

  test("skips containers that cannot be inspected", () => {
    // One unreadable container must not discard the rest of the sample.
    mockDocker({ ps: "gone\n" })
    expect(readContainers()).toEqual([])
  })

  test("returns null when docker ps fails and nothing was measured", () => {
    mockDocker({})
    expect(readContainers()).toBeNull()
  })

  test("still reports measured containers when docker ps fails", () => {
    // A runner whose daemon went away mid-job still knows what it saw.
    mockDocker({})
    const containers = readContainers({
      api: {
        name: "api",
        id: "c1",
        peak_rss_bytes: 1000,
        peak_pids: null,
        cpu_throttled_percent: null,
        oom_killed: false,
        exit_code: null,
        samples: 1,
      },
    })
    expect(containers).toHaveLength(1)
  })
})

describe("collectBuild", () => {
  test("assembles the payload for one image", () => {
    mockDocker({
      image: "2400000000",
      history: "500MB\tRUN apt-get update",
      ps: "c1\n",
      inspect: "/api\tfalse\t0\thealthy\t0",
    })
    const payload = collectBuild("sha256:aaa", 99, {
      dockerfilePath: "backend/Dockerfile",
    })
    expect(payload).not.toBeNull()
    expect(payload?.workflow_run_id).toBe(99)
    expect(payload?.image_ref).toBe("sha256:aaa")
    expect(payload?.dockerfile_path).toBe("backend/Dockerfile")
    expect(payload?.image_size_bytes).toBe(2_400_000_000)
    expect(payload?.layers).toHaveLength(1)
    expect(payload?.containers).toHaveLength(1)
    // Without an opted-in metadata file there is no cache data to report, and
    // 0 would read as "every layer missed".
    expect(payload?.cache_hit_ratio).toBeNull()
  })

  test("reads the cache-hit ratio when a metadata file is supplied", () => {
    mockDocker({ image: "100", history: "0B\tRUN true", ps: "" })
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gsops-"))
    const file = path.join(dir, "metadata.json")
    fs.writeFileSync(
      file,
      JSON.stringify({ steps: [{ cached: true }, { cached: false }] }),
    )
    try {
      const payload = collectBuild("sha256:aaa", 1, { metadataPath: file })
      expect(payload?.cache_hit_ratio).toBe(0.5)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })

  test("returns null when the image cannot be inspected at all", () => {
    // An empty row would make observed_builds misleading, so nothing is posted.
    mockDocker({})
    expect(collectBuild("sha256:missing", 1)).toBeNull()
  })
})
