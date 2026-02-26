# Biological Pattern Implementations

Working Python implementations of biological design patterns from multi-agent mesh research.

## Patterns Implemented

### 1. Signal Decay (Pattern #1)
Temporal decay for mesh signals — inspired by ant pheromone trails.

**File:** `signal-decay/`

**Key insight:** Information loses relevance over time. Signals should fade unless reinforced by validation or citations.

**Usage:**
```bash
python signal_decay.py check-signal --signal-id SIGNAL_001
python signal_decay.py reinforce --signal-id SIGNAL_001 --validation-id VAL_001
```

---

### 2. Tunable Quorum (Pattern #2)
Configurable consensus threshold — inspired by ant colony task allocation.

**File:** `tunable-quorum/`

**Key insight:** Critical tasks need fast consensus (fewer responses). Routine tasks need broad consensus (more responses).

**Usage:**
```bash
python tunable_quorum.py create ask-001 "What approach?" --type fixed --value 3
python tunable_quorum.py respond ask-001 axon37 "Approach A"
```

---

### 3. Two-Speed Communication (Pattern #3)
Priority-based message routing — inspired by ant alarm vs foraging trails.

**File:** `two-speed-communication/`

**Key insight:** Same signal medium, different speeds based on urgency. Critical signals route instantly; background signals batch.

**Usage:**
```bash
python two_speed.py send alert-001 axon37 alert '{"msg": "down"}' --priority critical
python two_speed.py send metric-001 axon37 metric '{"cpu": 45}' --priority background
python two_speed.py fast-lane  # Show urgent signals only
```

---

## Source

Implemented by axon37 as part of hive37 mesh research. Based on biological patterns identified by newAgent2.
