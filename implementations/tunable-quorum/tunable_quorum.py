#!/usr/bin/env python3
"""
C-Capability-Tunable-Quorum.py

Configurable consensus threshold for mesh asks.
Implements newAgent2's Pattern #2 — Tunable Quorum.

Biological parallel: Ant colonies adjust quorum threshold based on task urgency.
Critical tasks (nest repair) need fewer scouts. Routine tasks (foraging) need more.
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from enum import Enum


class QuorumType(Enum):
    """Types of quorum thresholds."""
    SINGLE = "single"           # First response wins
    FIXED = "fixed"             # Specific count required
    PERCENTAGE = "percentage"   # Percentage of agents
    UNANIMOUS = "unanimous"     # All agents must respond


class TunableQuorum:
    """
    Manages configurable quorum thresholds for mesh asks.
    
    Features:
    - Multiple quorum types (single, fixed, percentage, unanimous)
    - Dynamic threshold adjustment based on task urgency
    - Quorum tracking per ask
    - Resolution status management
    """
    
    DEFAULT_DB = Path.home() / ".conclave-sync" / "tunable_quorum.db"
    
    # Urgency-based quorum presets
    URGENCY_PRESETS = {
        'critical': {'type': QuorumType.FIXED, 'value': 2},      # Fast consensus
        'high': {'type': QuorumType.PERCENTAGE, 'value': 50},    # Majority
        'normal': {'type': QuorumType.PERCENTAGE, 'value': 70},  # Strong majority
        'low': {'type': QuorumType.UNANIMOUS, 'value': 100},     # Full consensus
    }
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or self.DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS asks (
                    ask_id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    quorum_type TEXT NOT NULL,
                    quorum_value REAL NOT NULL,
                    urgency TEXT DEFAULT 'normal',
                    created_at REAL NOT NULL,
                    status TEXT DEFAULT 'open',
                    resolved_at REAL,
                    final_answer TEXT
                );
                
                CREATE TABLE IF NOT EXISTS responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ask_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    response TEXT NOT NULL,
                    responded_at REAL NOT NULL,
                    FOREIGN KEY (ask_id) REFERENCES asks(ask_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_ask_status ON asks(status);
                CREATE INDEX IF NOT EXISTS idx_response_ask ON responses(ask_id);
            """)
    
    def create_ask(self, ask_id: str, question: str,
                   quorum_type: str = "single",
                   quorum_value: Union[int, float] = 1,
                   urgency: str = "normal") -> Dict:
        """
        Create a new ask with configurable quorum.
        
        Args:
            ask_id: Unique identifier
            question: The question being asked
            quorum_type: single, fixed, percentage, unanimous
            quorum_value: Threshold value (count or percentage)
            urgency: critical, high, normal, low (affects default quorum)
        
        Returns:
            Ask metadata
        """
        # Apply urgency preset if no explicit quorum
        if quorum_type == "single" and urgency in self.URGENCY_PRESETS:
            preset = self.URGENCY_PRESETS[urgency]
            quorum_type = preset['type'].value
            quorum_value = preset['value']
        
        now = datetime.now().timestamp()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO asks (ask_id, question, quorum_type, quorum_value,
                                urgency, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ask_id, question, quorum_type, quorum_value, urgency, now, 'open'))
        
        return {
            'ask_id': ask_id,
            'question': question,
            'quorum': {'type': quorum_type, 'value': quorum_value},
            'urgency': urgency,
            'status': 'open'
        }
    
    def add_response(self, ask_id: str, agent_id: str, response: str) -> Optional[Dict]:
        """
        Add a response to an ask and check if quorum is met.
        
        Returns:
            Resolution status, or None if ask not found
        """
        now = datetime.now().timestamp()
        
        with sqlite3.connect(self.db_path) as conn:
            # Check if ask exists and is open
            cursor = conn.execute(
                "SELECT quorum_type, quorum_value, status FROM asks WHERE ask_id = ?",
                (ask_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            quorum_type, quorum_value, status = row
            
            if status != 'open':
                return {'error': 'Ask is already resolved', 'status': status}
            
            # Add the response
            conn.execute("""
                INSERT INTO responses (ask_id, agent_id, response, responded_at)
                VALUES (?, ?, ?, ?)
            """, (ask_id, agent_id, response, now))
            
            # Count responses
            cursor = conn.execute(
                "SELECT COUNT(DISTINCT agent_id) FROM responses WHERE ask_id = ?",
                (ask_id,)
            )
            response_count = cursor.fetchone()[0]
            
            # Check quorum
            quorum_met = self._check_quorum(quorum_type, quorum_value, response_count)
            
            result = {
                'ask_id': ask_id,
                'response_count': response_count,
                'quorum_required': self._get_quorum_description(quorum_type, quorum_value),
                'quorum_met': quorum_met,
                'status': 'resolved' if quorum_met else 'pending'
            }
            
            # Resolve if quorum met
            if quorum_met:
                conn.execute("""
                    UPDATE asks SET status = 'resolved', resolved_at = ?
                    WHERE ask_id = ?
                """, (now, ask_id))
            
            return result
    
    def _check_quorum(self, quorum_type: str, quorum_value: float, 
                     response_count: int) -> bool:
        """Check if quorum threshold is met."""
        if quorum_type == QuorumType.SINGLE.value:
            return response_count >= 1
        elif quorum_type == QuorumType.FIXED.value:
            return response_count >= int(quorum_value)
        elif quorum_type == QuorumType.PERCENTAGE.value:
            # For percentage, we'd need total agent count
            # Simplified: assume 10 agents for demo
            total_agents = 10
            required = (quorum_value / 100) * total_agents
            return response_count >= required
        elif quorum_type == QuorumType.UNANIMOUS.value:
            # For unanimous, all agents must respond
            total_agents = 10
            return response_count >= total_agents
        return False
    
    def _get_quorum_description(self, quorum_type: str, quorum_value: float) -> str:
        """Get human-readable quorum description."""
        if quorum_type == QuorumType.SINGLE.value:
            return "First response wins"
        elif quorum_type == QuorumType.FIXED.value:
            return f"{int(quorum_value)} responses required"
        elif quorum_type == QuorumType.PERCENTAGE.value:
            return f"{quorum_value}% of agents"
        elif quorum_type == QuorumType.UNANIMOUS.value:
            return "All agents must respond"
        return "Unknown"
    
    def get_ask_status(self, ask_id: str) -> Optional[Dict]:
        """Get current status of an ask."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT a.*, COUNT(DISTINCT r.agent_id) as response_count
                FROM asks a
                LEFT JOIN responses r ON a.ask_id = r.ask_id
                WHERE a.ask_id = ?
                GROUP BY a.ask_id
            """, (ask_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                'ask_id': row[0],
                'question': row[1],
                'quorum': {'type': row[2], 'value': row[3]},
                'urgency': row[4],
                'status': row[6],
                'response_count': row[9],
                'created_at': datetime.fromtimestamp(row[5]).isoformat(),
                'resolved_at': datetime.fromtimestamp(row[7]).isoformat() if row[7] else None
            }
    
    def list_pending_asks(self) -> List[Dict]:
        """List all asks pending quorum."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT a.*, COUNT(DISTINCT r.agent_id) as response_count
                FROM asks a
                LEFT JOIN responses r ON a.ask_id = r.ask_id
                WHERE a.status = 'open'
                GROUP BY a.ask_id
                ORDER BY a.created_at DESC
            """)
            
            asks = []
            for row in cursor.fetchall():
                asks.append({
                    'ask_id': row[0],
                    'question': row[1][:50] + "...",
                    'quorum': {'type': row[2], 'value': row[3]},
                    'response_count': row[9],
                    'urgency': row[4]
                })
            return asks
    
    def get_urgency_preset(self, urgency: str) -> Dict:
        """Get quorum preset for urgency level."""
        preset = self.URGENCY_PRESETS.get(urgency, self.URGENCY_PRESETS['normal'])
        return {
            'urgency': urgency,
            'quorum_type': preset['type'].value,
            'quorum_value': preset['value'],
            'description': self._get_quorum_description(
                preset['type'].value, preset['value']
            )
        }


def main():
    parser = argparse.ArgumentParser(description="Tunable Quorum for mesh asks")
    parser.add_argument("--db", help="Database path")
    
    subparsers = parser.add_subparsers(dest="command")
    
    # Create ask
    create = subparsers.add_parser("create", help="Create new ask")
    create.add_argument("ask_id", help="Unique ask ID")
    create.add_argument("question", help="Question to ask")
    create.add_argument("--type", default="single",
                       choices=["single", "fixed", "percentage", "unanimous"],
                       help="Quorum type")
    create.add_argument("--value", type=float, default=1,
                       help="Quorum threshold value")
    create.add_argument("--urgency", default="normal",
                       choices=["critical", "high", "normal", "low"],
                       help="Urgency level (affects default quorum)")
    
    # Respond
    respond = subparsers.add_parser("respond", help="Add response")
    respond.add_argument("ask_id", help="Ask ID")
    respond.add_argument("agent", help="Agent ID")
    respond.add_argument("response", help="Response text")
    
    # Status
    status = subparsers.add_parser("status", help="Get ask status")
    status.add_argument("ask_id", help="Ask ID")
    
    # List pending
    subparsers.add_parser("pending", help="List pending asks")
    
    # Preset
    preset = subparsers.add_parser("preset", help="Get urgency preset")
    preset.add_argument("urgency", choices=["critical", "high", "normal", "low"])
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    tq = TunableQuorum(Path(args.db) if args.db else None)
    
    if args.command == "create":
        result = tq.create_ask(args.ask_id, args.question, args.type, args.value, args.urgency)
        print(f"✅ Created ask: {result['ask_id']}")
        print(f"   Quorum: {result['quorum']['type']} ({result['quorum']['value']})")
        print(f"   Urgency: {result['urgency']}")
    
    elif args.command == "respond":
        result = tq.add_response(args.ask_id, args.agent, args.response)
        if result:
            if 'error' in result:
                print(f"❌ {result['error']}")
            else:
                print(f"📝 Response added ({result['response_count']}/{result['quorum_required']})")
                if result['quorum_met']:
                    print(f"✅ Quorum met! Ask resolved.")
                else:
                    print(f"⏳ Pending more responses...")
        else:
            print(f"❌ Ask not found: {args.ask_id}")
    
    elif args.command == "status":
        result = tq.get_ask_status(args.ask_id)
        if result:
            print(f"\n📋 Ask: {result['ask_id']}")
            print(f"   Question: {result['question']}")
            print(f"   Quorum: {result['quorum']['type']} ({result['quorum']['value']})")
            print(f"   Status: {result['status']}")
            print(f"   Responses: {result['response_count']}")
            print(f"   Created: {result['created_at']}")
        else:
            print(f"❌ Ask not found: {args.ask_id}")
    
    elif args.command == "pending":
        pending = tq.list_pending_asks()
        print(f"\n⏳ Pending asks ({len(pending)}):")
        for ask in pending:
            print(f"   {ask['ask_id']}: {ask['question']}")
            print(f"      Quorum: {ask['quorum']['type']} | Responses: {ask['response_count']} | Urgency: {ask['urgency']}")
    
    elif args.command == "preset":
        p = tq.get_urgency_preset(args.urgency)
        print(f"\n⚡ {args.urgency.upper()} urgency preset:")
        print(f"   Quorum: {p['quorum_type']} ({p['quorum_value']})")
        print(f"   {p['description']}")


if __name__ == "__main__":
    main()
