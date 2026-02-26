#!/usr/bin/env python3
"""
C-Capability-Two-Speed-Communication.py

Priority-based message routing for mesh signals.
Implements newAgent2's Pattern #3 — Two-Speed Communication.

Biological parallel: Ant colonies use fast pheromone trails for alerts
and slow recruitment for routine foraging. Same signal medium, different
speeds based on urgency.
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum
import heapq


class PriorityLevel(Enum):
    """Signal priority levels — determines routing speed."""
    CRITICAL = 1   # Immediate broadcast (alarms, failures)
    HIGH = 2       # Fast relay (asks, urgent responses)
    NORMAL = 3     # Standard routing (capabilities, knowledge)
    LOW = 4        # Background sync (metrics, logs)
    BACKGROUND = 5 # Deferred/batched (analytics, archives)


class SpeedChannel(Enum):
    """Communication channels with different latency guarantees."""
    INSTANT = "instant"      # < 1 second (critical alerts)
    FAST = "fast"            # < 5 seconds (high priority)
    STANDARD = "standard"    # < 30 seconds (normal)
    BATCHED = "batched"      # < 5 minutes (low)
    DEFERRED = "deferred"    # Next cycle (background)


CHANNEL_LATENCY = {
    SpeedChannel.INSTANT: 1,
    SpeedChannel.FAST: 5,
    SpeedChannel.STANDARD: 30,
    SpeedChannel.BATCHED: 300,
    SpeedChannel.DEFERRED: 3600,
}


class TwoSpeedCommunication:
    """
    Routes mesh signals at different speeds based on priority.
    
    Features:
    - Priority-based channel assignment
    - Fast lane for urgent signals
    - Batching for background traffic
    - Latency guarantees per channel
    """
    
    DEFAULT_DB = Path.home() / ".conclave-sync" / "two_speed_comm.db"
    
    # Priority → Channel mapping
    PRIORITY_CHANNELS = {
        PriorityLevel.CRITICAL: SpeedChannel.INSTANT,
        PriorityLevel.HIGH: SpeedChannel.FAST,
        PriorityLevel.NORMAL: SpeedChannel.STANDARD,
        PriorityLevel.LOW: SpeedChannel.BATCHED,
        PriorityLevel.BACKGROUND: SpeedChannel.DEFERRED,
    }
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or self.DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    scheduled_for REAL NOT NULL,
                    delivered_at REAL,
                    delivery_status TEXT DEFAULT 'pending'
                );
                
                CREATE INDEX IF NOT EXISTS idx_priority ON signals(priority);
                CREATE INDEX IF NOT EXISTS idx_channel ON signals(channel);
                CREATE INDEX IF NOT EXISTS idx_scheduled ON signals(scheduled_for);
                CREATE INDEX IF NOT EXISTS idx_status ON signals(delivery_status);
                
                CREATE TABLE IF NOT EXISTS channel_stats (
                    channel TEXT PRIMARY KEY,
                    total_signals INTEGER DEFAULT 0,
                    delivered_count INTEGER DEFAULT 0,
                    avg_latency_ms REAL,
                    last_updated REAL
                );
            """)
    
    def send_signal(self, signal_id: str, agent_id: str, 
                   signal_type: str, payload: Dict,
                   priority: str = "normal") -> Dict:
        """
        Send a signal with priority-based routing.
        
        Args:
            signal_id: Unique signal identifier
            agent_id: Sending agent
            signal_type: Type of signal (ask, response, capability, etc.)
            payload: Signal content
            priority: critical, high, normal, low, background
        
        Returns:
            Routing details including channel and expected latency
        """
        now = datetime.now()
        priority_enum = PriorityLevel[priority.upper()]
        channel = self.PRIORITY_CHANNELS[priority_enum]
        
        # Calculate scheduled delivery time
        latency_seconds = CHANNEL_LATENCY[channel]
        scheduled_for = now + timedelta(seconds=latency_seconds)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO signals 
                (signal_id, agent_id, signal_type, priority, channel,
                 payload, created_at, scheduled_for)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_id, agent_id, signal_type, priority_enum.value,
                channel.value, json.dumps(payload), now.timestamp(),
                scheduled_for.timestamp()
            ))
        
        return {
            'signal_id': signal_id,
            'priority': priority,
            'channel': channel.value,
            'expected_latency_sec': latency_seconds,
            'scheduled_for': scheduled_for.isoformat(),
            'status': 'queued'
        }
    
    def process_channel(self, channel: str, max_signals: int = 100) -> List[Dict]:
        """
        Process all pending signals for a channel.
        
        Returns:
            List of signals ready for delivery
        """
        now = datetime.now().timestamp()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT signal_id, agent_id, signal_type, priority,
                       channel, payload, created_at, scheduled_for
                FROM signals
                WHERE channel = ? AND delivery_status = 'pending'
                  AND scheduled_for <= ?
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
            """, (channel, now, max_signals))
            
            signals = []
            for row in cursor.fetchall():
                signals.append({
                    'signal_id': row[0],
                    'agent_id': row[1],
                    'signal_type': row[2],
                    'priority': row[3],
                    'channel': row[4],
                    'payload': json.loads(row[5]),
                    'created_at': datetime.fromtimestamp(row[6]).isoformat(),
                    'scheduled_for': datetime.fromtimestamp(row[7]).isoformat(),
                })
                
                # Mark as delivered
                conn.execute("""
                    UPDATE signals 
                    SET delivery_status = 'delivered', delivered_at = ?
                    WHERE signal_id = ?
                """, (now, row[0]))
            
            return signals
    
    def get_queue_status(self) -> Dict:
        """Get current queue status across all channels."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT channel, priority, COUNT(*) as count,
                       MIN(scheduled_for) as next_delivery
                FROM signals
                WHERE delivery_status = 'pending'
                GROUP BY channel, priority
                ORDER BY channel, priority
            """)
            
            status = {}
            for row in cursor.fetchall():
                channel, priority, count, next_delivery = row
                if channel not in status:
                    status[channel] = {'total_pending': 0, 'by_priority': {}}
                status[channel]['total_pending'] += count
                status[channel]['by_priority'][priority] = count
                if next_delivery:
                    status[channel]['next_delivery'] = datetime.fromtimestamp(next_delivery).isoformat()
            
            return status
    
    def get_fast_lane_signals(self, max_age_seconds: int = 60) -> List[Dict]:
        """
        Get all signals in fast/instant lanes.
        For monitoring critical and high-priority traffic.
        """
        cutoff = (datetime.now() - timedelta(seconds=max_age_seconds)).timestamp()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT signal_id, agent_id, signal_type, priority,
                       channel, payload, created_at
                FROM signals
                WHERE priority <= 2 AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 50
            """, (cutoff,))
            
            return [{
                'signal_id': row[0],
                'agent_id': row[1],
                'signal_type': row[2],
                'priority': row[3],
                'channel': row[4],
                'payload': json.loads(row[5]),
                'created_at': datetime.fromtimestamp(row[6]).isoformat(),
            } for row in cursor.fetchall()]
    
    def batch_background_signals(self, batch_size: int = 10) -> List[Dict]:
        """
        Collect background signals for batch processing.
        
        Returns:
            Batch of low-priority signals ready for deferred processing
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT signal_id, agent_id, signal_type, payload
                FROM signals
                WHERE channel = 'deferred' AND delivery_status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
            """, (batch_size,))
            
            batch = []
            for row in cursor.fetchall():
                batch.append({
                    'signal_id': row[0],
                    'agent_id': row[1],
                    'signal_type': row[2],
                    'payload': json.loads(row[3]),
                })
            
            return batch
    
    def get_channel_latency_stats(self) -> Dict:
        """Get latency statistics per channel."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT channel,
                       COUNT(*) as total,
                       AVG(delivered_at - created_at) as avg_latency,
                       MAX(delivered_at - created_at) as max_latency
                FROM signals
                WHERE delivery_status = 'delivered'
                  AND delivered_at IS NOT NULL
                GROUP BY channel
            """)
            
            stats = {}
            for row in cursor.fetchall():
                channel, total, avg_lat, max_lat = row
                target = CHANNEL_LATENCY.get(SpeedChannel(channel), 30)
                stats[channel] = {
                    'total_delivered': total,
                    'avg_latency_sec': round(avg_lat, 2) if avg_lat else None,
                    'max_latency_sec': round(max_lat, 2) if max_lat else None,
                    'target_latency_sec': target,
                    'meeting_sla': avg_lat <= target if avg_lat else None
                }
            
            return stats


def main():
    parser = argparse.ArgumentParser(
        description="Two-speed communication for mesh signals"
    )
    parser.add_argument("--db", help="Database path")
    
    subparsers = parser.add_subparsers(dest="command")
    
    # Send command
    send = subparsers.add_parser("send", help="Send a signal")
    send.add_argument("signal_id", help="Unique signal ID")
    send.add_argument("agent", help="Agent ID")
    send.add_argument("type", help="Signal type")
    send.add_argument("payload", help="JSON payload")
    send.add_argument("--priority", default="normal",
                     choices=["critical", "high", "normal", "low", "background"],
                     help="Signal priority")
    
    # Process command
    process = subparsers.add_parser("process", help="Process channel queue")
    process.add_argument("channel",
                        choices=["instant", "fast", "standard", "batched", "deferred"],
                        help="Channel to process")
    
    # Status command
    subparsers.add_parser("status", help="Get queue status")
    
    # Fast lane command
    subparsers.add_parser("fast-lane", help="Show recent fast/instant signals")
    
    # Batch command
    batch = subparsers.add_parser("batch", help="Get batch of background signals")
    batch.add_argument("--size", type=int, default=10, help="Batch size")
    
    # Stats command
    subparsers.add_parser("stats", help="Get latency statistics")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    tsc = TwoSpeedCommunication(Path(args.db) if args.db else None)
    
    if args.command == "send":
        result = tsc.send_signal(
            args.signal_id, args.agent, args.type,
            json.loads(args.payload), args.priority
        )
        print(f"📤 Signal queued: {result['signal_id']}")
        print(f"   Priority: {result['priority']}")
        print(f"   Channel: {result['channel']}")
        print(f"   Expected latency: {result['expected_latency_sec']}s")
    
    elif args.command == "process":
        signals = tsc.process_channel(args.channel)
        print(f"📨 Processed {len(signals)} signals from {args.channel} channel")
        for sig in signals[:5]:
            print(f"   {sig['signal_id']} ({sig['signal_type']})")
    
    elif args.command == "status":
        status = tsc.get_queue_status()
        print("\n📊 Queue Status")
        print("=" * 50)
        for channel, info in status.items():
            print(f"\n{channel.upper()}:")
            print(f"   Pending: {info['total_pending']}")
            print(f"   By priority: {info['by_priority']}")
            if 'next_delivery' in info:
                print(f"   Next: {info['next_delivery']}")
    
    elif args.command == "fast-lane":
        signals = tsc.get_fast_lane_signals()
        print(f"\n⚡ Fast Lane Signals ({len(signals)} recent)")
        print("=" * 50)
        for sig in signals[:10]:
            emoji = "🔴" if sig['priority'] == 1 else "🟠"
            print(f"{emoji} {sig['signal_id']} ({sig['signal_type']}) - {sig['agent_id']}")
    
    elif args.command == "batch":
        batch = tsc.batch_background_signals(args.size)
        print(f"\n📦 Background Batch ({len(batch)} signals)")
        for sig in batch:
            print(f"   {sig['signal_id']}: {sig['signal_type']}")
    
    elif args.command == "stats":
        stats = tsc.get_channel_latency_stats()
        print("\n📈 Latency Statistics")
        print("=" * 60)
        print(f"{'Channel':<12} {'Avg (s)':<10} {'Target':<10} {'SLA':<8}")
        print("-" * 60)
        for channel, info in stats.items():
            sla = "✅" if info['meeting_sla'] else "❌"
            avg = f"{info['avg_latency_sec']:.1f}" if info['avg_latency_sec'] else "N/A"
            print(f"{channel:<12} {avg:<10} {info['target_latency_sec']:<10} {sla:<8}")


if __name__ == "__main__":
    main()
