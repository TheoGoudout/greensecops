package main

import (
	"math"
	"sort"
	"time"
)

// TopProcess is one entry of the JSON array printed to stdout.
type TopProcess struct {
	PID        int     `json:"pid"`
	Name       string  `json:"name"`
	CPUPercent float64 `json:"cpu_percent"`
	MemPercent float64 `json:"mem_percent"`
	MemRSSMB   float64 `json:"mem_rss_mb"`
}

const (
	topPercentDefault = 0.10
	topFloor          = 5
	topCap            = 20
)

func round1(v float64) float64 {
	return math.Round(v*10) / 10
}

// topN returns how many processes to keep for a given total count, per the
// 5-10% floor/cap rule: at least topFloor (so quiet boxes still return a
// useful list) and at most topCap (bounds payload size on busy boxes).
func topN(total int, percent float64) int {
	n := int(math.Ceil(float64(total) * percent))
	if n < topFloor {
		n = topFloor
	}
	if n > topCap {
		n = topCap
	}
	if n > total {
		n = total
	}
	return n
}

// rankTopProcesses computes cpu_percent/mem_percent from two snapshots taken
// `elapsed` apart and returns the top N processes by cpu_percent (ties
// broken by mem_percent), N chosen by topN().
func rankTopProcesses(before, after map[int]procSnapshot, elapsed time.Duration, memTotalKB uint64, percent float64) []TopProcess {
	elapsedSec := elapsed.Seconds()
	if elapsedSec <= 0 {
		elapsedSec = 0.001
	}

	all := make([]TopProcess, 0, len(after))
	for pid, a := range after {
		b, ok := before[pid]
		if !ok {
			// New pid that appeared mid-window — no baseline to diff
			// against, skip rather than report a misleading spike.
			continue
		}
		deltaTicks := float64(a.utime+a.stime) - float64(b.utime+b.stime)
		if deltaTicks < 0 {
			deltaTicks = 0
		}
		cpuPercent := (deltaTicks / clockTicksPerSec) / elapsedSec * 100.0

		var memPercent float64
		if memTotalKB > 0 {
			memPercent = float64(a.rssKB) / float64(memTotalKB) * 100.0
		}

		all = append(all, TopProcess{
			PID:        pid,
			Name:       a.name,
			CPUPercent: round1(cpuPercent),
			MemPercent: round1(memPercent),
			MemRSSMB:   round1(float64(a.rssKB) / 1024.0),
		})
	}

	sort.Slice(all, func(i, j int) bool {
		if all[i].CPUPercent != all[j].CPUPercent {
			return all[i].CPUPercent > all[j].CPUPercent
		}
		return all[i].MemPercent > all[j].MemPercent
	})

	n := topN(len(all), percent)
	if n > len(all) {
		n = len(all)
	}
	return all[:n]
}
