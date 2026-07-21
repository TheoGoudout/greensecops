package main

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// clockTicksPerSec is CLOCKS_PER_SEC / USER_HZ, effectively always 100 on
// Linux regardless of architecture. Reading it dynamically would require
// cgo (sysconf) or the golang.org/x/sys module; hardcoding avoids both,
// keeping this binary dependency-free.
const clockTicksPerSec = 100

type procSnapshot struct {
	pid   int
	name  string
	utime uint64
	stime uint64
	rssKB uint64
}

func listPids(procRoot string) ([]int, error) {
	entries, err := os.ReadDir(procRoot)
	if err != nil {
		return nil, err
	}
	pids := make([]int, 0, len(entries))
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		pids = append(pids, pid)
	}
	return pids, nil
}

func readComm(procRoot string, pid int) string {
	data, err := os.ReadFile(filepath.Join(procRoot, strconv.Itoa(pid), "comm"))
	if err != nil {
		return "unknown"
	}
	return strings.TrimSpace(string(data))
}

// readStat parses /proc/[pid]/stat fields 14 (utime) and 15 (stime), in
// clock ticks. The comm field (2nd, parenthesized) may itself contain spaces
// or parentheses, so we split on the LAST ')' rather than naive whitespace
// splitting of the whole line.
func readStat(procRoot string, pid int) (utime, stime uint64, err error) {
	data, err := os.ReadFile(filepath.Join(procRoot, strconv.Itoa(pid), "stat"))
	if err != nil {
		return 0, 0, err
	}
	line := string(data)
	closeParen := strings.LastIndex(line, ")")
	if closeParen == -1 || closeParen+2 >= len(line) {
		return 0, 0, fmt.Errorf("malformed stat line for pid %d", pid)
	}
	fields := strings.Fields(line[closeParen+2:])
	// fields[0] here is `state` (the 3rd field overall); utime is the 14th
	// field overall, i.e. fields[11] in this remainder slice.
	const utimeIdx = 11
	const stimeIdx = 12
	if len(fields) <= stimeIdx {
		return 0, 0, fmt.Errorf("too few fields in stat line for pid %d", pid)
	}
	utime, err = strconv.ParseUint(fields[utimeIdx], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	stime, err = strconv.ParseUint(fields[stimeIdx], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	return utime, stime, nil
}

// readRSSKB parses the VmRSS line from /proc/[pid]/status, in kB.
func readRSSKB(procRoot string, pid int) (uint64, error) {
	f, err := os.Open(filepath.Join(procRoot, strconv.Itoa(pid), "status"))
	if err != nil {
		return 0, err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "VmRSS:") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			return 0, fmt.Errorf("malformed VmRSS line")
		}
		return strconv.ParseUint(fields[1], 10, 64)
	}
	return 0, fmt.Errorf("VmRSS not found for this pid")
}

// readMemTotalKB parses MemTotal from /proc/meminfo, in kB.
func readMemTotalKB(procRoot string) (uint64, error) {
	f, err := os.Open(filepath.Join(procRoot, "meminfo"))
	if err != nil {
		return 0, err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "MemTotal:") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			return 0, fmt.Errorf("malformed MemTotal line")
		}
		return strconv.ParseUint(fields[1], 10, 64)
	}
	return 0, fmt.Errorf("MemTotal not found")
}

// snapshotAll reads utime/stime/rss/name for every currently-running pid.
// A pid that disappears mid-read (exited between listPids and the read) is
// silently skipped rather than treated as fatal — expected on a busy runner.
func snapshotAll(procRoot string) map[int]procSnapshot {
	pids, err := listPids(procRoot)
	if err != nil {
		return map[int]procSnapshot{}
	}
	out := make(map[int]procSnapshot, len(pids))
	for _, pid := range pids {
		utime, stime, err := readStat(procRoot, pid)
		if err != nil {
			continue
		}
		rss, _ := readRSSKB(procRoot, pid) // 0 if unavailable, not fatal
		out[pid] = procSnapshot{
			pid:   pid,
			name:  readComm(procRoot, pid),
			utime: utime,
			stime: stime,
			rssKB: rss,
		}
	}
	return out
}
