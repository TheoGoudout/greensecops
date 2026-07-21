package main

import (
	"testing"
	"time"
)

func TestTopN_FloorAndCap(t *testing.T) {
	cases := []struct {
		total   int
		percent float64
		want    int
	}{
		{total: 3, percent: 0.10, want: 3},   // below floor, but can't exceed total
		{total: 20, percent: 0.10, want: 5},  // 10% of 20 is 2, floor kicks in to 5
		{total: 60, percent: 0.10, want: 6},  // 10% of 60 is 6, no floor/cap needed
		{total: 200, percent: 0.10, want: 20}, // 10% of 200 is 20, at the cap exactly
		{total: 500, percent: 0.10, want: 20}, // 10% of 500 is 50, cap kicks in to 20
	}
	for _, c := range cases {
		got := topN(c.total, c.percent)
		if got != c.want {
			t.Errorf("topN(%d, %v) = %d, want %d", c.total, c.percent, got, c.want)
		}
	}
}

func TestRankTopProcesses_SortsByCPUDescending(t *testing.T) {
	before := map[int]procSnapshot{
		1: {pid: 1, name: "busy", utime: 0, stime: 0},
		2: {pid: 2, name: "idle", utime: 0, stime: 0},
		3: {pid: 3, name: "medium", utime: 0, stime: 0},
	}
	after := map[int]procSnapshot{
		1: {pid: 1, name: "busy", utime: 100, stime: 0, rssKB: 1024},
		2: {pid: 2, name: "idle", utime: 1, stime: 0, rssKB: 512},
		3: {pid: 3, name: "medium", utime: 50, stime: 0, rssKB: 2048},
	}

	result := rankTopProcesses(before, after, 1*time.Second, 100000, 1.0) // percent=1.0 keeps all (still floored to 5, but only 3 exist)

	if len(result) != 3 {
		t.Fatalf("got %d results, want 3", len(result))
	}
	if result[0].Name != "busy" || result[1].Name != "medium" || result[2].Name != "idle" {
		t.Fatalf("got order %v, %v, %v — want busy, medium, idle", result[0].Name, result[1].Name, result[2].Name)
	}
}

func TestRankTopProcesses_SkipsNewPidsWithoutBaseline(t *testing.T) {
	before := map[int]procSnapshot{
		1: {pid: 1, name: "existing", utime: 0, stime: 0},
	}
	after := map[int]procSnapshot{
		1: {pid: 1, name: "existing", utime: 10, stime: 0},
		2: {pid: 2, name: "brand-new", utime: 5, stime: 0}, // appeared mid-window, no baseline
	}

	result := rankTopProcesses(before, after, 1*time.Second, 100000, 1.0)

	if len(result) != 1 {
		t.Fatalf("got %d results, want 1 (new pid should be skipped)", len(result))
	}
	if result[0].Name != "existing" {
		t.Fatalf("got %q, want %q", result[0].Name, "existing")
	}
}

func TestRankTopProcesses_ComputesExpectedCPUPercent(t *testing.T) {
	before := map[int]procSnapshot{1: {pid: 1, utime: 0, stime: 0}}
	// 100 ticks (utime+stime) over 1 second, clockTicksPerSec=100 -> 1 full
	// core-second of work in 1 wall-clock second -> 100% cpu.
	after := map[int]procSnapshot{1: {pid: 1, utime: 100, stime: 0}}

	result := rankTopProcesses(before, after, 1*time.Second, 0, 1.0)

	if len(result) != 1 {
		t.Fatalf("got %d results, want 1", len(result))
	}
	if result[0].CPUPercent != 100.0 {
		t.Fatalf("got cpu_percent=%v, want 100.0", result[0].CPUPercent)
	}
}

func TestRankTopProcesses_ZeroMemTotalYieldsZeroPercent(t *testing.T) {
	before := map[int]procSnapshot{1: {pid: 1}}
	after := map[int]procSnapshot{1: {pid: 1, rssKB: 4096}}

	result := rankTopProcesses(before, after, 1*time.Second, 0, 1.0)

	if result[0].MemPercent != 0 {
		t.Fatalf("got mem_percent=%v, want 0 when memTotalKB is 0", result[0].MemPercent)
	}
}
