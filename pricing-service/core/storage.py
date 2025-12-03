"""
Pricing Storage Layer - Persistent Data Management
SQLite for local dev, ready to swap for DynamoDB/Postgres in production.

Fortune 500 Standards:
- ACID transactions for config updates
- Idempotent operations (upsert semantics)
- Query optimization via indexes
- Migration-friendly schema
"""

import sqlite3
import json
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime

from core.models import PricingConfig, MeteringEvent

logger = logging.getLogger("PricingStorage")
logger.setLevel(logging.INFO)

# Database path
DB_DIR = Path(__file__).parent.parent / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "pricing.db"


class PricingStorage:
    """
    Storage adapter for pricing configurations and metering events.
    
    Architecture:
    - Single SQLite file for simplicity in local dev
    - JSON columns for flexible schema (document store pattern)
    - Indexed columns for query performance
    - Ready to subclass for cloud databases
    
    Tables:
    - pricing_configs: Master pricing configurations
    - metering_events: Billing events (for audit/future use)
    """
    
    def __init__(self, db_path: Path = DB_PATH):
        """Initialize storage with database connection."""
        self.db_path = db_path
        self._init_db()
        logger.info(f"PricingStorage initialized: {self.db_path}")
    
    def _init_db(self):
        """Create tables and indexes if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table: pricing_configs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pricing_configs (
                config_id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                name TEXT,
                status TEXT DEFAULT 'draft',
                currency TEXT DEFAULT 'USD',
                created_at TEXT,
                updated_at TEXT,
                data_json TEXT NOT NULL
            )
        """)
        
        # Indexes for query performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pricing_product 
            ON pricing_configs(product_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pricing_status 
            ON pricing_configs(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pricing_created 
            ON pricing_configs(created_at DESC)
        """)
        
        # Table: metering_events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metering_events (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                product_id TEXT NOT NULL,
                feature_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Indexes for metering queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metering_feature 
            ON metering_events(feature_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metering_timestamp 
            ON metering_events(timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metering_product 
            ON metering_events(product_id)
        """)
        
        conn.commit()
        conn.close()
        logger.info("Database schema initialized with indexes")
    
    # ========================================================================
    # PRICING CONFIG OPERATIONS
    # ========================================================================
    
    def save_config(self, config: PricingConfig) -> None:
        """
        Save or update pricing configuration (upsert).
        
        Args:
            config: PricingConfig to persist
            
        Idempotent: Safe to call multiple times with same config_id.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            now = datetime.utcnow().isoformat()
            
            cursor.execute("""
                INSERT OR REPLACE INTO pricing_configs 
                (config_id, product_id, name, status, currency, created_at, updated_at, data_json)
                VALUES (?, ?, ?, ?, ?, COALESCE(
                    (SELECT created_at FROM pricing_configs WHERE config_id = ?),
                    ?
                ), ?, ?)
            """, (
                config.pricing_config_id,
                config.product_id,
                config.name,
                config.status,
                config.currency,
                config.pricing_config_id,  # For COALESCE check
                now,  # Default created_at if new
                now,  # Always update updated_at
                config.model_dump_json()
            ))
            
            conn.commit()
            logger.info(f"Config saved: {config.pricing_config_id}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to save config {config.pricing_config_id}: {e}")
            raise
        finally:
            conn.close()
    
    def get_config(self, config_id: str) -> Optional[PricingConfig]:
        """
        Retrieve pricing configuration by ID.
        
        Args:
            config_id: Unique configuration identifier
            
        Returns:
            PricingConfig if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT data_json FROM pricing_configs WHERE config_id = ?
            """, (config_id,))
            
            row = cursor.fetchone()
            if row:
                config = PricingConfig.model_validate_json(row[0])
                logger.debug(f"Config retrieved: {config_id}")
                return config
            
            logger.debug(f"Config not found: {config_id}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve config {config_id}: {e}")
            raise
        finally:
            conn.close()
    
    def list_configs(
        self,
        product_id: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 100
    ) -> List[PricingConfig]:
        """
        List pricing configurations with optional filters.
        
        Args:
            product_id: Filter by product (optional)
            status_filter: Filter by status (draft/active/archived)
            limit: Maximum results to return
            
        Returns:
            List of PricingConfig objects
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Build query dynamically based on filters
            query = "SELECT data_json FROM pricing_configs WHERE 1=1"
            params = []
            
            if product_id:
                query += " AND product_id = ?"
                params.append(product_id)
            
            if status_filter:
                query += " AND status = ?"
                params.append(status_filter)
            
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            configs = [PricingConfig.model_validate_json(row[0]) for row in rows]
            logger.info(f"Listed {len(configs)} configs")
            return configs
            
        except Exception as e:
            logger.error(f"Failed to list configs: {e}")
            raise
        finally:
            conn.close()
    
    def delete_config(self, config_id: str) -> bool:
        """
        Hard delete pricing configuration.
        
        Note: Prefer soft delete (status='archived') in production for audit trail.
        
        Args:
            config_id: Configuration to delete
            
        Returns:
            True if deleted, False if not found
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM pricing_configs WHERE config_id = ?
            """, (config_id,))
            
            deleted = cursor.rowcount > 0
            conn.commit()
            
            if deleted:
                logger.info(f"Config deleted: {config_id}")
            else:
                logger.warning(f"Config not found for deletion: {config_id}")
            
            return deleted
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete config {config_id}: {e}")
            raise
        finally:
            conn.close()
    
    # ========================================================================
    # METERING EVENT OPERATIONS
    # ========================================================================
    
    def save_metering_event(self, event: MeteringEvent) -> None:
        """
        Save metering event (idempotent by event_id).
        
        Args:
            event: MeteringEvent to persist
            
        Idempotent: Duplicate event_id will be ignored (INSERT OR IGNORE).
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO metering_events
                (event_id, timestamp, product_id, feature_id, event_type, data_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.timestamp,
                event.product_id,
                event.feature_id,
                event.type,
                event.model_dump_json()
            ))
            
            if cursor.rowcount > 0:
                logger.info(f"Metering event saved: {event.event_id}")
            else:
                logger.debug(f"Metering event duplicate ignored: {event.event_id}")
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to save metering event {event.event_id}: {e}")
            raise
        finally:
            conn.close()
    
    def get_metering_events(
        self,
        feature_id: Optional[str] = None,
        product_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000
    ) -> List[MeteringEvent]:
        """
        Query metering events with filters.
        
        Args:
            feature_id: Filter by feature
            product_id: Filter by product
            start_time: Filter by timestamp >= (ISO8601)
            end_time: Filter by timestamp <= (ISO8601)
            limit: Max results
            
        Returns:
            List of MeteringEvent objects
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            query = "SELECT data_json FROM metering_events WHERE 1=1"
            params = []
            
            if feature_id:
                query += " AND feature_id = ?"
                params.append(feature_id)
            
            if product_id:
                query += " AND product_id = ?"
                params.append(product_id)
            
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)
            
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            events = [MeteringEvent.model_validate_json(row[0]) for row in rows]
            logger.info(f"Retrieved {len(events)} metering events")
            return events
            
        except Exception as e:
            logger.error(f"Failed to query metering events: {e}")
            raise
        finally:
            conn.close()
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics for monitoring.
        
        Returns:
            Dict with counts and health metrics
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Count configs by status
            cursor.execute("""
                SELECT status, COUNT(*) FROM pricing_configs GROUP BY status
            """)
            config_counts = dict(cursor.fetchall())
            
            # Count metering events
            cursor.execute("SELECT COUNT(*) FROM metering_events")
            event_count = cursor.fetchone()[0]
            
            # Database size
            db_size_mb = self.db_path.stat().st_size / (1024 * 1024)
            
            stats = {
                "configs_by_status": config_counts,
                "total_configs": sum(config_counts.values()),
                "total_metering_events": event_count,
                "database_size_mb": round(db_size_mb, 2),
                "database_path": str(self.db_path)
            }
            
            logger.info(f"Storage stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            raise
        finally:
            conn.close()
