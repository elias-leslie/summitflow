package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/mem"
	"github.com/shirou/gopsutil/v3/net"
	"github.com/tklauser/go-sysconf"
)

var ticksPerSecond uint64

type issue struct {
	Source string `json:"source"`
	Code   string `json:"code"`
}

type issues struct {
	list []issue
	seen map[issue]bool
}

func (e *issues) add(source string, err error) {
	if err == nil {
		return
	}
	code := "unavailable"
	if errors.Is(err, os.ErrPermission) || errors.Is(err, syscall.EACCES) {
		code = "permission_denied"
	} else if errors.Is(err, os.ErrNotExist) {
		code = "not_found"
	} else if errors.Is(err, io.ErrUnexpectedEOF) {
		code = "parse_error"
	} else if strings.HasPrefix(err.Error(), "parse:") {
		code = "parse_error"
	}
	v := issue{source, code}
	if !e.seen[v] {
		e.seen[v] = true
		e.list = append(e.list, v)
	}
}

type hostSample struct {
	CPUBusyPct           *float64 `json:"cpu_busy_pct"`
	MemoryTotalBytes     *uint64  `json:"memory_total_bytes"`
	MemoryAvailableBytes *uint64  `json:"memory_available_bytes"`
	SwapUsedBytes        *uint64  `json:"swap_used_bytes"`
	DiskTotalBytes       *uint64  `json:"disk_total_bytes"`
	DiskFreeBytes        *uint64  `json:"disk_free_bytes"`
	CPUSomeAvg10Pct      *float64 `json:"cpu_some_avg10_pct"`
	MemorySomeAvg10Pct   *float64 `json:"memory_some_avg10_pct"`
	IOSomeAvg10Pct       *float64 `json:"io_some_avg10_pct"`
	NetRXBytes           *uint64  `json:"net_rx_bytes"`
	NetTXBytes           *uint64  `json:"net_tx_bytes"`
	DiskReadBytes        *uint64  `json:"disk_read_bytes"`
	DiskWriteBytes       *uint64  `json:"disk_write_bytes"`
}

type serviceSample struct {
	Source             string  `json:"source"`
	CPUUsageUsec       *uint64 `json:"cpu_usage_usec"`
	MemoryCurrentBytes *uint64 `json:"memory_current_bytes"`
	IOReadBytes        *uint64 `json:"io_read_bytes"`
	IOWriteBytes       *uint64 `json:"io_write_bytes"`
}

type processSample struct {
	PID         int      `json:"pid"`
	StartTicks  uint64   `json:"start_ticks"`
	Name        string   `json:"name"`
	CPUUserNS   uint64   `json:"cpu_user_ns"`
	CPUSystemNS uint64   `json:"cpu_system_ns"`
	RSSBytes    uint64   `json:"rss_bytes"`
	ReadBytes   *uint64  `json:"read_bytes"`
	WriteBytes  *uint64  `json:"write_bytes"`
	Reasons     []string `json:"leader_reasons"`
}

type sample struct {
	Schema                  int             `json:"schema"`
	SampledAt               time.Time       `json:"sampled_at"`
	ElapsedNS               *int64          `json:"elapsed_ns"`
	Mode                    string          `json:"mode"`
	Provider                string          `json:"provider"`
	DurationNS              int64           `json:"duration_ns"`
	Host                    hostSample      `json:"host"`
	Service                 *serviceSample  `json:"service"`
	Processes               []processSample `json:"processes"`
	ProcessesSeen           int             `json:"processes_seen"`
	ProcessPermissionDenied int             `json:"processes_permission_denied"`
	ProcessExitedDuringScan int             `json:"processes_exited"`
	Errors                  []issue         `json:"errors"`
}

type cpuTotals struct{ idle, total uint64 }

func readCPU() (cpuTotals, error) {
	f, err := os.Open("/proc/stat")
	if err != nil {
		return cpuTotals{}, err
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	if !s.Scan() {
		return cpuTotals{}, fmt.Errorf("parse: /proc/stat cpu line: %w", io.ErrUnexpectedEOF)
	}
	fields := strings.Fields(s.Text())
	if len(fields) < 6 || fields[0] != "cpu" {
		return cpuTotals{}, fmt.Errorf("parse: /proc/stat cpu fields")
	}
	var out cpuTotals
	for i, field := range fields[1:] {
		if i >= 8 {
			break
		} // guest and guest_nice are already included in user/nice.
		n, err := strconv.ParseUint(field, 10, 64)
		if err != nil {
			return cpuTotals{}, fmt.Errorf("parse: cpu tick: %w", err)
		}
		out.total += n
		if i == 3 || i == 4 {
			out.idle += n
		}
	}
	return out, nil
}

func psi(path string) (*float64, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	for s.Scan() {
		fields := strings.Fields(s.Text())
		if len(fields) == 0 || fields[0] != "some" {
			continue
		}
		for _, field := range fields[1:] {
			if !strings.HasPrefix(field, "avg10=") {
				continue
			}
			v, err := strconv.ParseFloat(strings.TrimPrefix(field, "avg10="), 64)
			if err != nil {
				return nil, fmt.Errorf("parse: PSI avg10: %w", err)
			}
			return &v, nil
		}
	}
	if err := s.Err(); err != nil {
		return nil, err
	}
	return nil, fmt.Errorf("parse: PSI some avg10 missing")
}

func collectHost(previous *cpuTotals, errs *issues) (hostSample, *cpuTotals) {
	var h hostSample
	cur, cpuErr := readCPU()
	if cpuErr != nil {
		errs.add("/proc/stat", cpuErr)
	} else if previous != nil && cur.total > previous.total && cur.idle >= previous.idle && cur.idle-previous.idle <= cur.total-previous.total {
		v := 100 * float64((cur.total-previous.total)-(cur.idle-previous.idle)) / float64(cur.total-previous.total)
		if !math.IsNaN(v) && v >= 0 && v <= 100 {
			h.CPUBusyPct = &v
		}
	}
	vm, err := mem.VirtualMemory()
	if err != nil {
		errs.add("memory", err)
	} else {
		h.MemoryTotalBytes, h.MemoryAvailableBytes = &vm.Total, &vm.Available
	}
	swap, err := mem.SwapMemory()
	if err != nil {
		errs.add("swap", err)
	} else {
		h.SwapUsedBytes = &swap.Used
	}
	usage, err := disk.Usage("/")
	if err != nil {
		errs.add("disk:/", err)
	} else {
		h.DiskTotalBytes, h.DiskFreeBytes = &usage.Total, &usage.Free
	}
	for _, item := range []struct {
		path   string
		target **float64
	}{
		{"/proc/pressure/cpu", &h.CPUSomeAvg10Pct},
		{"/proc/pressure/memory", &h.MemorySomeAvg10Pct},
		{"/proc/pressure/io", &h.IOSomeAvg10Pct},
	} {
		*item.target, err = psi(item.path)
		if err != nil {
			errs.add(item.path, err)
		}
	}
	interfaces, err := net.IOCounters(true)
	if err != nil {
		errs.add("net", err)
	} else {
		var rx, tx uint64
		for _, n := range interfaces {
			if n.Name != "lo" {
				rx += n.BytesRecv
				tx += n.BytesSent
			}
		}
		h.NetRXBytes, h.NetTXBytes = &rx, &tx
	}
	devices, err := disk.IOCounters()
	if err != nil {
		errs.add("disk_io", err)
	} else {
		blocks, blockErr := os.ReadDir("/sys/block")
		if blockErr != nil {
			errs.add("/sys/block", blockErr)
		} else {
			var rd, wr uint64
			matched := 0
			for _, b := range blocks {
				name := b.Name()
				if strings.HasPrefix(name, "loop") || strings.HasPrefix(name, "ram") {
					continue
				}
				if d, ok := devices[name]; ok {
					rd += d.ReadBytes
					wr += d.WriteBytes
					matched++
				}
			}
			if matched == 0 {
				errs.add("disk_io", fmt.Errorf("parse: no whole devices matched"))
			} else {
				h.DiskReadBytes, h.DiskWriteBytes = &rd, &wr
			}
		}
	}
	if cpuErr != nil {
		return h, nil
	}
	return h, &cur
}

func parseKeyValue(path, key string) (*uint64, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[0] == key {
			v, err := strconv.ParseUint(fields[1], 10, 64)
			if err != nil {
				return nil, fmt.Errorf("parse: %s: %w", key, err)
			}
			return &v, nil
		}
	}
	return nil, fmt.Errorf("parse: %s missing", key)
}

func collectService(path string, errs *issues) *serviceSample {
	if path == "" {
		return nil
	}
	if !filepath.IsAbs(path) {
		path = filepath.Join("/sys/fs/cgroup", path)
	}
	s := &serviceSample{Source: "cgroup2"}
	var err error
	s.CPUUsageUsec, err = parseKeyValue(filepath.Join(path, "cpu.stat"), "usage_usec")
	if err != nil {
		errs.add("cgroup2:cpu.stat", err)
	}
	data, err := os.ReadFile(filepath.Join(path, "memory.current"))
	if err != nil {
		errs.add("cgroup2:memory.current", err)
	} else {
		v, parseErr := strconv.ParseUint(strings.TrimSpace(string(data)), 10, 64)
		if parseErr != nil {
			errs.add("cgroup2:memory.current", fmt.Errorf("parse: %w", parseErr))
		} else {
			s.MemoryCurrentBytes = &v
		}
	}
	data, err = os.ReadFile(filepath.Join(path, "io.stat"))
	if err != nil {
		errs.add("cgroup2:io.stat", err)
	} else {
		var rd, wr uint64
		gotR, gotW := false, false
		for _, line := range strings.Split(string(data), "\n") {
			fields := strings.Fields(line)
			if len(fields) < 2 {
				continue
			}
			for _, field := range fields[1:] {
				key, raw, ok := strings.Cut(field, "=")
				if !ok || (key != "rbytes" && key != "wbytes") {
					continue
				}
				v, parseErr := strconv.ParseUint(raw, 10, 64)
				if parseErr != nil {
					errs.add("cgroup2:io.stat", fmt.Errorf("parse: %w", parseErr))
					continue
				}
				if key == "rbytes" {
					rd += v
					gotR = true
				} else {
					wr += v
					gotW = true
				}
			}
		}
		if gotR {
			s.IOReadBytes = &rd
		} else {
			errs.add("cgroup2:io.stat:rbytes", fmt.Errorf("parse: missing"))
		}
		if gotW {
			s.IOWriteBytes = &wr
		} else {
			errs.add("cgroup2:io.stat:wbytes", fmt.Errorf("parse: missing"))
		}
	}
	return s
}

func parseStat(pid int, data []byte) (processSample, error) {
	line := string(data)
	open, close := strings.IndexByte(line, '('), strings.LastIndexByte(line, ')')
	if open < 0 || close < open {
		return processSample{}, fmt.Errorf("parse: process stat comm")
	}
	f := strings.Fields(line[close+1:])
	if len(f) < 22 {
		return processSample{}, fmt.Errorf("parse: process stat fields")
	}
	get := func(i int) (uint64, error) { return strconv.ParseUint(f[i], 10, 64) }
	user, err := get(11)
	if err != nil {
		return processSample{}, fmt.Errorf("parse: utime: %w", err)
	}
	system, err := get(12)
	if err != nil {
		return processSample{}, fmt.Errorf("parse: stime: %w", err)
	}
	start, err := get(19)
	if err != nil {
		return processSample{}, fmt.Errorf("parse: starttime: %w", err)
	}
	rss, err := get(21)
	if err != nil {
		return processSample{}, fmt.Errorf("parse: rss: %w", err)
	}
	return processSample{PID: pid, StartTicks: start, Name: line[open+1 : close], CPUUserNS: user * uint64(time.Second) / ticksPerSecond, CPUSystemNS: system * uint64(time.Second) / ticksPerSecond, RSSBytes: rss * uint64(os.Getpagesize()), Reasons: []string{}}, nil
}

func parseProcIO(path string) (*uint64, *uint64, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, err
	}
	var rd, wr *uint64
	for _, line := range strings.Split(string(data), "\n") {
		key, raw, ok := strings.Cut(strings.TrimSpace(line), ":")
		if !ok || (key != "read_bytes" && key != "write_bytes") {
			continue
		}
		v, parseErr := strconv.ParseUint(strings.TrimSpace(raw), 10, 64)
		if parseErr != nil {
			return nil, nil, fmt.Errorf("parse: process io: %w", parseErr)
		}
		if key == "read_bytes" {
			rd = &v
		} else {
			wr = &v
		}
	}
	if rd == nil || wr == nil {
		return nil, nil, fmt.Errorf("parse: process io fields missing")
	}
	return rd, wr, nil
}

func collectProcesses(errs *issues) ([]processSample, int, int, int) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		errs.add("/proc", err)
		return []processSample{}, 0, 0, 0
	}
	rows := make([]processSample, 0, len(entries)/4)
	seen, denied, exited := 0, 0, 0
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || pid <= 0 {
			continue
		}
		seen++
		path := filepath.Join("/proc", entry.Name())
		data, err := os.ReadFile(filepath.Join(path, "stat"))
		if err != nil {
			if errors.Is(err, os.ErrPermission) {
				denied++
			} else if errors.Is(err, os.ErrNotExist) {
				exited++
			}
			errs.add("/proc/<pid>/stat", err)
			continue
		}
		p, err := parseStat(pid, data)
		if err != nil {
			errs.add("/proc/<pid>/stat", err)
			continue
		}
		p.ReadBytes, p.WriteBytes, err = parseProcIO(filepath.Join(path, "io"))
		if err != nil {
			if errors.Is(err, os.ErrPermission) {
				denied++
			} else if errors.Is(err, os.ErrNotExist) {
				exited++
			}
			errs.add("/proc/<pid>/io", err)
		}
		rows = append(rows, p)
	}
	return rows, seen, denied, exited
}

type identity struct {
	pid   int
	start uint64
}

func baseline(rows []processSample, previous map[identity]processSample) []processSample {
	selected := map[identity]map[string]bool{}
	mark := func(p processSample, reason string) {
		id := identity{p.PID, p.StartTicks}
		if selected[id] == nil {
			selected[id] = map[string]bool{}
		}
		selected[id][reason] = true
	}
	ranked := append([]processSample(nil), rows...)
	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].RSSBytes != ranked[j].RSSBytes {
			return ranked[i].RSSBytes > ranked[j].RSSBytes
		}
		if ranked[i].PID != ranked[j].PID {
			return ranked[i].PID < ranked[j].PID
		}
		return ranked[i].StartTicks < ranked[j].StartTicks
	})
	for i := 0; i < len(ranked) && i < 10; i++ {
		mark(ranked[i], "rss")
	}
	type candidate struct {
		p     processSample
		delta uint64
	}
	var cpu, ioRows []candidate
	for _, p := range rows {
		old, ok := previous[identity{p.PID, p.StartTicks}]
		if !ok {
			continue
		}
		currentCPU, oldCPU := p.CPUUserNS+p.CPUSystemNS, old.CPUUserNS+old.CPUSystemNS
		if currentCPU >= oldCPU {
			cpu = append(cpu, candidate{p, currentCPU - oldCPU})
		}
		if p.ReadBytes != nil && p.WriteBytes != nil && old.ReadBytes != nil && old.WriteBytes != nil && *p.ReadBytes >= *old.ReadBytes && *p.WriteBytes >= *old.WriteBytes {
			ioRows = append(ioRows, candidate{p, (*p.ReadBytes - *old.ReadBytes) + (*p.WriteBytes - *old.WriteBytes)})
		}
	}
	order := func(a []candidate) {
		sort.Slice(a, func(i, j int) bool {
			if a[i].delta != a[j].delta {
				return a[i].delta > a[j].delta
			}
			if a[i].p.PID != a[j].p.PID {
				return a[i].p.PID < a[j].p.PID
			}
			return a[i].p.StartTicks < a[j].p.StartTicks
		})
	}
	order(cpu)
	order(ioRows)
	for i := 0; i < len(cpu) && i < 10; i++ {
		mark(cpu[i].p, "cpu")
	}
	for i := 0; i < len(ioRows) && i < 10; i++ {
		mark(ioRows[i].p, "io")
	}
	out := make([]processSample, 0, len(selected))
	for _, p := range rows {
		if reasons, ok := selected[identity{p.PID, p.StartTicks}]; ok {
			for _, name := range []string{"cpu", "rss", "io"} {
				if reasons[name] {
					p.Reasons = append(p.Reasons, name)
				}
			}
			out = append(out, p)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].PID != out[j].PID {
			return out[i].PID < out[j].PID
		}
		return out[i].StartTicks < out[j].StartTicks
	})
	return out
}

func index(rows []processSample) map[identity]processSample {
	m := make(map[identity]processSample, len(rows))
	for _, p := range rows {
		m[identity{p.PID, p.StartTicks}] = p
	}
	return m
}

func main() {
	clockTicks, clockErr := sysconf.Sysconf(sysconf.SC_CLK_TCK)
	if clockErr != nil || clockTicks <= 0 {
		fmt.Fprintln(os.Stderr, "unable to read Linux clock ticks:", clockErr)
		os.Exit(1)
	}
	ticksPerSecond = uint64(clockTicks)
	mode := flag.String("mode", "baseline", "baseline or detail")
	samples := flag.Int("samples", 1, "finite sample count")
	interval := flag.Int("interval-ms", -1, "sample start interval in milliseconds")
	servicePath := flag.String("service-cgroup", "", "cgroup-v2 path")
	flag.Parse()
	if flag.NArg() != 0 || (*mode != "baseline" && *mode != "detail") || *samples < 1 || *interval < -1 {
		fmt.Fprintln(os.Stderr, "usage: run.sh --mode baseline|detail --samples N --interval-ms M [--service-cgroup PATH]")
		os.Exit(2)
	}
	if *interval == -1 {
		if *mode == "baseline" {
			*interval = 5000
		} else {
			*interval = 1000
		}
	}
	var previousStart time.Time
	var previousCPU *cpuTotals
	previousProcesses := map[identity]processSample{}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	for i := 0; i < *samples; i++ {
		if i > 0 {
			if until := previousStart.Add(time.Duration(*interval) * time.Millisecond).Sub(time.Now()); until > 0 {
				time.Sleep(until)
			}
		}
		started := time.Now()
		errs := &issues{list: []issue{}, seen: map[issue]bool{}}
		host, cpu := collectHost(previousCPU, errs)
		service := collectService(*servicePath, errs)
		rows, seen, denied, exited := collectProcesses(errs)
		output := rows
		if *mode == "baseline" {
			output = baseline(rows, previousProcesses)
		}
		var elapsed *int64
		if i > 0 {
			n := started.Sub(previousStart).Nanoseconds()
			elapsed = &n
		}
		result := sample{Schema: 1, SampledAt: started.UTC(), ElapsedNS: elapsed, Mode: *mode, Provider: "go-gopsutil", DurationNS: time.Since(started).Nanoseconds(), Host: host, Service: service, Processes: output, ProcessesSeen: seen, ProcessPermissionDenied: denied, ProcessExitedDuringScan: exited, Errors: errs.list}
		if err := encoder.Encode(result); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		previousStart, previousCPU, previousProcesses = started, cpu, index(rows)
	}
}
