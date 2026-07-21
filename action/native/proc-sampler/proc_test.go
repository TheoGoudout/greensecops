package main

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

func writeFixtureProc(t *testing.T, pid int, statLine, status, comm string) string {
	t.Helper()
	root := t.TempDir()
	writeFixtureProcInto(t, root, pid, statLine, status, comm)
	return root
}

func TestReadStat_Simple(t *testing.T) {
	root := writeFixtureProc(t, 1234, "1234 (bash) S 1 1234 1234 0 -1 4194304 0 0 0 0 100 50", "", "")

	utime, stime, err := readStat(root, 1234)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if utime != 100 || stime != 50 {
		t.Fatalf("got utime=%d stime=%d, want 100/50", utime, stime)
	}
}

func TestReadStat_CommWithParensAndSpaces(t *testing.T) {
	root := writeFixtureProc(t, 5678, "5678 (code helper (Renderer)) S 1 5678 5678 0 -1 4194304 0 0 0 0 300 20", "", "")

	utime, stime, err := readStat(root, 5678)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if utime != 300 || stime != 20 {
		t.Fatalf("got utime=%d stime=%d, want 300/20", utime, stime)
	}
}

func TestReadStat_Malformed(t *testing.T) {
	root := writeFixtureProc(t, 1, "not a valid stat line", "", "")
	if _, _, err := readStat(root, 1); err == nil {
		t.Fatal("expected error for malformed stat line, got nil")
	}
}

func TestReadStat_MissingPid(t *testing.T) {
	root := t.TempDir()
	if _, _, err := readStat(root, 9999); err == nil {
		t.Fatal("expected error for missing pid, got nil")
	}
}

func TestReadRSSKB(t *testing.T) {
	root := writeFixtureProc(t, 1, "", "Name:\tbash\nVmRSS:\t    2048 kB\nVmSize:\t   10000 kB\n", "")

	rss, err := readRSSKB(root, 1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rss != 2048 {
		t.Fatalf("got rss=%d, want 2048", rss)
	}
}

func TestReadRSSKB_Missing(t *testing.T) {
	root := writeFixtureProc(t, 1, "", "Name:\tbash\nVmSize:\t   10000 kB\n", "")
	if _, err := readRSSKB(root, 1); err == nil {
		t.Fatal("expected error when VmRSS is absent, got nil")
	}
}

func TestReadMemTotalKB(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "meminfo"), []byte("MemTotal:       16384000 kB\nMemFree:  1000 kB\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	total, err := readMemTotalKB(root)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if total != 16384000 {
		t.Fatalf("got %d, want 16384000", total)
	}
}

func TestReadComm_FallsBackWhenMissing(t *testing.T) {
	root := t.TempDir()
	name := readComm(root, 1)
	if name != "unknown" {
		t.Fatalf("got %q, want %q", name, "unknown")
	}
}

func TestSnapshotAll_SkipsUnreadablePids(t *testing.T) {
	root := t.TempDir()
	// pid 1: complete and readable
	writeFixtureProcInto(t, root, 1, "1 (init) S 0 1 1 0 -1 4194304 0 0 0 0 10 5", "VmRSS:\t100 kB\n", "init")
	// pid 2: directory exists but stat is malformed — should be skipped, not fatal
	writeFixtureProcInto(t, root, 2, "garbage", "", "")

	snap := snapshotAll(root)
	if _, ok := snap[1]; !ok {
		t.Fatal("expected pid 1 present in snapshot")
	}
	if _, ok := snap[2]; ok {
		t.Fatal("expected pid 2 (malformed stat) to be skipped")
	}
}

func writeFixtureProcInto(t *testing.T, root string, pid int, statLine, status, comm string) {
	t.Helper()
	dir := filepath.Join(root, strconv.Itoa(pid))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if statLine != "" {
		_ = os.WriteFile(filepath.Join(dir, "stat"), []byte(statLine), 0o644)
	}
	if status != "" {
		_ = os.WriteFile(filepath.Join(dir, "status"), []byte(status), 0o644)
	}
	if comm != "" {
		_ = os.WriteFile(filepath.Join(dir, "comm"), []byte(comm), 0o644)
	}
}
