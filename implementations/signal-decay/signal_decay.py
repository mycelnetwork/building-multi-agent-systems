#!/usr/bin/env python3
"""
C-Capability-Signal-Decay.py

Signal decay for DCI mesh traces — implements newAgent2's Pattern #1.
Older signals lose visibility/vitality over time unless reinforced.
Biological parallel: Pheromone trails that don't lead to food evaporate.
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SignalDecay:
    """
    Manages temporal decay of mesh signals.
    
    Core concept: Signal visibility = f(age, reinforcement_count, type)
    - Older signals decay (lower visibility)
    - Reinforced signals refresh (reset decay)
    - Different types have different decay rates (urgent vs background)
    """
    
    DEFAULT_DECAY_RATES = {
        'ask': 0.9,        # 10% visibility loss per day (high priority)
        'knowledge': 0.95, # 5% visibility loss per day (medium)
        'capability': 0.97, # 3% visibility loss per day (slow)
        'background': 0.85, # 15% visibility loss per day (fast decay)
    }
    
    def __init__(self, db_path: Optional[Path] = None, 
                 decay_rates: Optional[Dict[str, float]] = None):
        """
        Initialize signal decay manager.
        
        Args:
            db_path: SQLite database path (default: ~/.conclave-sync/signal_decay.db)
            decay_rates: Custom decay rates per signal type
        """
        self.db_path = db_path or Path.home() / ".conclave-sync" / "signal_decay.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.decay_rates = decay_rates or self.DEFAULT_DECAY_RATES.copy()
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_reinforced REAL,
                    reinforcement_count INTEGER DEFAULT 1,
                    base_visibility REAL DEFAULT 1.0,
                    current_visibility REAL DEFAULT 1.0,
                    content_hash TEXT,
                    metadata TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_agent ON signals(agent_id);
                CREATE INDEX IF NOT EXISTS idx_type ON signals(signal_type);
                CREATE INDEX IF NOT EXISTS idx_visibility ON signals(current_visibility);
                CREATE INDEX IF NOT EXISTS idx_created ON signals(created_at);
                
                CREATE TABLE IF NOT EXISTS decay_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL,
                    old_visibility REAL,
                    new_visibility REAL,
                    decay_applied_at REAL,
                    reason TEXT
                );
            """)
    
    def register_signal(self, signal_id: str, agent_id: str, 
                       signal_type: str, content_hash: str,
                       metadata: Optional[Dict] = None) -> float:
        """
        Register a new signal in the decay system.
        
        Returns:
            Initial visibility (1.0 for new signals)
        """
        now = datetime.now().timestamp()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO signals 
                (signal_id, agent_id, signal_type, created_at, 
                 last_reinforced, reinforcement_count, base_visibility,
                 current_visibility, content_hash, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_id, agent_id, signal_type, now, now, 1, 1.0, 1.0,
                content_hash, json.dumps(metadata) if metadata else None
            ))
        
        return 1.0
    
    def reinforce_signal(self, signal_id: str, 
                        reinforcement_type: str = "view") -> Optional[float]:
        """
        Reinforce a signal (reset decay).
        
        Args:
            signal_id: Signal to reinforce
            reinforcement_type: Type of reinforcement (view, response, validation, etc.)
        
        Returns:
            New visibility level, or None if signal not found
        """
        now = datetime.now().timestamp()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT reinforcement_count FROM signals WHERE signal_id = ?",
                (signal_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            new_count = row[0] + 1
            # Reinforcement boosts visibility (max 1.0)
            new_visibility = min(1.0, 0.8 + (0.2 * (1 - 1/new_count)))
            
            conn.execute("""
                UPDATE signals 
                SET reinforcement_count = ?,
                    last_reinforced = ?,
                    current_visibility = ?
                WHERE signal_id = ?
            """, (new_count, now, new_visibility, signal_id))
            
            return new_visibility
    
    def calculate_decay(self, signal_id: str, 
                       as_of: Optional[datetime] = None) -> Optional[float]:
        """
        Calculate current visibility after decay.
        
        Args:
            signal_id: Signal to check
            as_of: Calculate as of specific time (default: now)
        
        Returns:
            Current visibility (0.0 to 1.0), or None if not found
        """
        as_of = as_of or datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT signal_type, last_reinforced, current_visibility 
                   FROM signals WHERE signal_id = ?""",
                (signal_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            signal_type, last_reinforced, current_vis = row
            decay_rate = self.decay_rates.get(signal_type, 0.95)
            
            # Calculate days since last reinforcement
            last_time = datetime.fromtimestamp(last_reinforced)
            days_elapsed = (as_of - last_time).total_seconds() / 86400
            
            # Apply decay: visibility * (decay_rate ^ days)
            new_visibility = current_vis * (decay_rate ** days_elapsed)
            
            return max(0.0, new_visibility)
    
    def apply_decay(self, signal_id: str) -> Optional[float]:
        """
        Apply decay to a signal and update database.
        
        Returns:
            New visibility after decay
        """
        new_visibility = self.calculate_decay(signal_id)
        
        if new_visibility is None:
            return None
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT current_visibility FROM signals WHERE signal_id = ?",
                (signal_id,)
            )
            old_visibility = cursor.fetchone()[0]
            
            conn.execute(
                "UPDATE signals SET current_visibility = ? WHERE signal_id = ?",
                (new_visibility, signal_id)
            )
            
            # Log the decay
            conn.execute("""
                INSERT INTO decay_log (signal_id, old_visibility, 
                                      new_visibility, decay_applied_at, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (signal_id, old_visibility, new_visibility, 
                  datetime.now().timestamp(), "scheduled_decay"))
        
        return new_visibility
    
    def get_visible_signals(self, min_visibility: float = 0.5,
                           signal_type: Optional[str] = None,
                           limit: int = 100) -> List[Dict]:
        """
        Get signals above visibility threshold.
        
        Automatically applies decay before returning.
        
        Args:
            min_visibility: Minimum visibility (0.0 to 1.0)
            signal_type: Filter by type (optional)
            limit: Max results
        
        Returns:
            List of visible signals sorted by visibility (highest first)
        """
        # First apply decay to all signals
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT signal_id FROM signals")
            for row in cursor:
                self.apply_decay(row[0])
            
            # Now query visible signals
            if signal_type:
                cursor = conn.execute("""
                    SELECT signal_id, agent_id, signal_type, 
                           current_visibility, reinforcement_count,
                           datetime(created_at, 'unixepoch') as created,
                           datetime(last_reinforced, 'unixepoch') as reinforced
                    FROM signals 
                    WHERE current_visibility >= ? AND signal_type = ?
                    ORDER BY current_visibility DESC, reinforcement_count DESC
                    LIMIT ?
                """, (min_visibility, signal_type, limit))
            else:
                cursor = conn.execute("""
                    SELECT signal_id, agent_id, signal_type, 
                           current_visibility, reinforcement_count,
                           datetime(created_at, 'unixepoch') as created,
                           datetime(last_reinforced, 'unixepoch') as reinforced
                    FROM signals 
                    WHERE current_visibility >= ?
                    ORDER BY current_visibility DESC, reinforcement_count DESC
                    LIMIT ?
                """, (min_visibility, limit))
            
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_signal_stats(self) -> Dict:
        """Get aggregate statistics about signal decay."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_signals,
                    AVG(current_visibility) as avg_visibility,
                    SUM(CASE WHEN current_visibility >= 0.8 THEN 1 ELSE 0 END) as high_visibility,
                    SUM(CASE WHEN current_visibility < 0.5 THEN 1 ELSE 0 END) as decayed_signals,
                    AVG(reinforcement_count) as avg_reinforcements
                FROM signals
            """)
            row = cursor.fetchone()
            
            return {
                'total_signals': row[0],
                'average_visibility': round(row[1], 3) if row[1] else 0,
                'high_visibility_count': row[2],
                'decayed_signals': row[3],
                'average_reinforcements': round(row[4], 2) if row[4] else 0
            }
    
    def prune_decayed_signals(self, threshold: float = 0.1) -> int:
        """
        Remove signals that have decayed below threshold.
        
        Returns:
            Number of signals pruned
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE current_visibility < ?",
                (threshold,)
            )
            count = cursor.fetchone()[0]
            
            conn.execute(
                "DELETE FROM signals WHERE current_visibility < ?",
                (threshold,)
            )
            
            return count


def main():
    parser = argparse.ArgumentParser(
        description="Signal decay system for DCI mesh"
    )
    parser.add_argument("--db", help="Database path")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Register command
    reg = subparsers.add_parser("register", help="Register a new signal")
    reg.add_argument("signal_id", help="Unique signal identifier")
    reg.add_argument("agent", help="Agent ID")
    reg.add_argument("type", choices=['ask', 'knowledge', 'capability', 'background'],
                    help="Signal type")
    reg.add_argument("hash", help="Content hash")
    
    # Reinforce command
    rein = subparsers.add_parser("reinforce", help="Reinforce a signal")
    rein.add_argument("signal_id", help="Signal to reinforce")
    
    # Decay command
    decay = subparsers.add_parser("decay", help="Apply decay to a signal")
    decay.add_argument("signal_id", help="Signal to decay")
    
    # Visible command
    vis = subparsers.add_parser("visible", help="Get visible signals")
    vis.add_argument("--min", type=float, default=0.5, 
                    help="Minimum visibility threshold")
    vis.add_argument("--type", help="Filter by type")
    vis.add_argument("--limit", type=int, default=50,
                    help="Max results")
    
    # Stats command
    subparsers.add_parser("stats", help="Get signal statistics")
    
    # Prune command
    prune = subparsers.add_parser("prune", help="Remove heavily decayed signals")
    prune.add_argument("--threshold", type=float, default=0.1,
                      help="Pruning threshold")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    sd = SignalDecay(db_path=Path(args.db) if args.db else None)
    
    if args.command == "register":
        vis = sd.register_signal(args.signal_id, args.agent, args.type, args.hash)
        print(f"✅ Registered {args.signal_id} (visibility: {vis:.2f})")
    
    elif args.command == "reinforce":
        new_vis = sd.reinforce_signal(args.signal_id)
        if new_vis:
            print(f"🔄 Reinforced {args.signal_id} (visibility: {new_vis:.2f})")
        else:
            print(f"❌ Signal not found: {args.signal_id}")
    
    elif args.command == "decay":
        new_vis = sd.apply_decay(args.signal_id)
        if new_vis:
            print(f"📉 Decayed {args.signal_id} (visibility: {new_vis:.2f})")
        else:
            print(f"❌ Signal not found: {args.signal_id}")
    
    elif args.command == "visible":
        signals = sd.get_visible_signals(args.min, args.type, args.limit)
        print(f"\n📊 Visible signals (≥{args.min} visibility):\n")
        print(f"{'Signal ID':<30} {'Agent':<15} {'Type':<12} {'Visibility':<10} {'Reinforced'}")
        print("-" * 80)
        for sig in signals:
            print(f"{sig['signal_id']:<30} {sig['agent_id']:<15} "
                  f"{sig['signal_type']:<12} {sig['current_visibility']:<10.2f} "
                  f"{sig['reinforcement_count']}x")
    
    elif args.command == "stats":
        stats = sd.get_signal_stats()
        print("\n📈 Signal Decay Statistics")
        print("=" * 40)
        print(f"Total signals: {stats['total_signals']}")
        print(f"Average visibility: {stats['average_visibility']:.2f}")
        print(f"High visibility (≥0.8): {stats['high_visibility_count']}")
        print(f"Decayed signals (<0.5): {stats['decayed_signals']}")
        print(f"Average reinforcements: {stats['average_reinforcements']}")
    
    elif args.command == "prune":
        count = sd.prune_decayed_signals(args.threshold)
        print(f"🗑️ Pruned {count} signals below {args.threshold} visibility")


if __name__ == "__main__":
    main()
