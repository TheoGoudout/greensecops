import { describe, expect, test } from "bun:test"
import * as fs from "node:fs"
import * as os from "node:os"
import * as path from "node:path"
import { parseSize, readCacheHitRatio, scrubInstruction } from "../docker"

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
