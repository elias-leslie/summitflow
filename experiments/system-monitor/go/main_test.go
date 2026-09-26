package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestParseStatHandlesParenthesesAndUsesCorrectFields(t *testing.T) {
	ticksPerSecond = 100
	fields := []string{"S", "1", "1", "1", "1", "1", "1", "1", "1", "1", "1", "250", "75", "1", "1", "1", "1", "1", "1", "321", "4096", "3"}
	p, err := parseStat(42, []byte("42 (name ) with space) "+strings.Join(fields, " ")))
	if err != nil {
		t.Fatal(err)
	}
	if p.Name != "name ) with space" || p.StartTicks != 321 || p.CPUUserNS != 2_500_000_000 || p.CPUSystemNS != 750_000_000 || p.RSSBytes != 3*uint64(os.Getpagesize()) {
		t.Fatalf("wrong stat fields: %+v", p)
	}
}

func TestBaselineFirstSampleOnlyRSSAndThenIntervalLeaders(t *testing.T) {
	a0 := processSample{PID: 1, StartTicks: 10, RSSBytes: 100, CPUUserNS: 1, ReadBytes: uintPtr(0), WriteBytes: uintPtr(0)}
	b0 := processSample{PID: 2, StartTicks: 20, RSSBytes: 200, CPUUserNS: 1, ReadBytes: uintPtr(0), WriteBytes: uintPtr(0)}
	first := baseline([]processSample{a0, b0}, map[identity]processSample{})
	for _, p := range first {
		if len(p.Reasons) != 1 || p.Reasons[0] != "rss" {
			t.Fatalf("first sample reasons: %+v", p.Reasons)
		}
	}
	a1 := a0
	a1.CPUUserNS = 10
	b1 := b0
	b1.ReadBytes = uintPtr(10)
	second := baseline([]processSample{a1, b1}, index([]processSample{a0, b0}))
	if len(second) != 2 || strings.Join(second[0].Reasons, ",") != "cpu,rss,io" || strings.Join(second[1].Reasons, ",") != "cpu,rss,io" {
		t.Fatalf("interval reasons: %+v", second)
	}
	reused := a1
	reused.StartTicks = 99
	reused.CPUUserNS = 100
	third := baseline([]processSample{reused, b1}, index([]processSample{a0, b0}))
	if strings.Join(third[0].Reasons, ",") != "rss" {
		t.Fatalf("reused PID received interval leader: %+v", third[0])
	}
}

func uintPtr(v uint64) *uint64 { return &v }

func TestProcessLeaderReasonsJSON(t *testing.T) {
	data, err := json.Marshal(processSample{Reasons: []string{}})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), `"leader_reasons":[]`) || strings.Contains(string(data), `"reasons":`) {
		t.Fatalf("unexpected process JSON: %s", data)
	}
}

func TestProcessCountJSONNames(t *testing.T) {
	data, err := json.Marshal(sample{})
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{`"processes_permission_denied":0`, `"processes_exited":0`} {
		if !strings.Contains(string(data), key) {
			t.Fatalf("missing %s in %s", key, data)
		}
	}
}
