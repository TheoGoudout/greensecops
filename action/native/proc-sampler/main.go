package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"
)

func main() {
	topPercent := flag.Float64("top-percent", topPercentDefault, "fraction of processes to keep (e.g. 0.10 for top 10%)")
	intervalMs := flag.Int("interval-ms", 200, "milliseconds between the two sampling passes used to compute cpu_percent")
	procRoot := flag.String("proc-root", "/proc", "root of the /proc filesystem (overridable for testing)")
	flag.Parse()

	before := snapshotAll(*procRoot)
	interval := time.Duration(*intervalMs) * time.Millisecond
	time.Sleep(interval)
	after := snapshotAll(*procRoot)

	memTotalKB, err := readMemTotalKB(*procRoot)
	if err != nil {
		memTotalKB = 0 // mem_percent will be 0 for every process, not fatal
	}

	result := rankTopProcesses(before, after, interval, memTotalKB, *topPercent)
	if result == nil {
		result = []TopProcess{}
	}

	enc := json.NewEncoder(os.Stdout)
	if err := enc.Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, "proc-sampler: failed to encode output:", err)
		os.Exit(1)
	}
}
