import aiosqlite
from pathlib import Path
from typing import Optional

import json
from src.config import DATABASE_PATH, logger
from src.storage.models import User, TrackedWallet, Subscription


class Database:
    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrency
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._create_tables()
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    async def _create_tables(self) -> None:
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            );

            CREATE TABLE IF NOT EXISTS tracked_wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                wallet_address TEXT NOT NULL,
                label TEXT,
                min_usd REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES users(chat_id),
                UNIQUE(chat_id, wallet_address)
            );

            CREATE TABLE IF NOT EXISTS processed_trades (
                trade_id TEXT PRIMARY KEY,
                wallet_address TEXT NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tracked_wallets_address
                ON tracked_wallets(wallet_address);
            CREATE INDEX IF NOT EXISTS idx_processed_trades_wallet
                ON processed_trades(wallet_address);

            CREATE TABLE IF NOT EXISTS subscriptions (
                chat_id INTEGER PRIMARY KEY,
                min_usd REAL DEFAULT 0,
                max_usd REAL,
                side TEXT,
                categories TEXT,
                whale_alert BOOLEAN DEFAULT FALSE,
                whale_min_usd REAL DEFAULT 10000,
                whale_max_trades INTEGER DEFAULT 3,
                FOREIGN KEY (chat_id) REFERENCES users(chat_id)
            );
        """)
        await self._conn.commit()

        # Migration: add columns to tracked_wallets if they don't exist
        for col, default in [("min_usd", "0"), ("is_active", "1")]:
            try:
                await self._conn.execute(f"ALTER TABLE tracked_wallets ADD COLUMN {col} DEFAULT {default}")
                await self._conn.commit()
            except Exception:
                pass  # Column already exists

        # Migration: add insider and whale columns to subscriptions
        migrations = [
            ("insider_alert", "FALSE"),
            ("insider_min_usd", "10000"),
            ("insider_max_trades", "3"),
            ("whale_alert", "FALSE"),
            ("whale_min_usd", "10000"),
        ]
        for col, default in migrations:
            try:
                await self._conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {col} DEFAULT {default}")
                await self._conn.commit()
            except Exception:
                pass  # Column already exists

    # User operations
    async def add_user(self, chat_id: int, username: Optional[str] = None) -> User:
        await self._conn.execute(
            """
            INSERT INTO users (chat_id, username) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET username = ?, is_active = TRUE
            """,
            (chat_id, username, username),
        )
        await self._conn.commit()
        return User(chat_id=chat_id, username=username)

    async def get_total_users(self) -> int:
        """Get total number of registered users."""
        cursor = await self._conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_user(self, chat_id: int) -> Optional[User]:
        cursor = await self._conn.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        if row:
            return User(
                chat_id=row["chat_id"],
                username=row["username"],
                created_at=row["created_at"],
                is_active=row["is_active"],
            )
        return None

    # Wallet tracking operations
    async def add_tracked_wallet(
        self, chat_id: int, address: str, label: Optional[str] = None, min_usd: float = 0.0
    ) -> bool:
        try:
            # Normalize address to lowercase
            address = address.lower()
            await self._conn.execute(
                """
                INSERT INTO tracked_wallets (chat_id, wallet_address, label, min_usd)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, address, label, min_usd),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False  # Already tracking this wallet

    async def remove_tracked_wallet(self, chat_id: int, address: str) -> bool:
        address = address.lower()
        cursor = await self._conn.execute(
            "DELETE FROM tracked_wallets WHERE chat_id = ? AND wallet_address = ?",
            (chat_id, address),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_tracked_wallets(self, chat_id: int) -> list[TrackedWallet]:
        cursor = await self._conn.execute(
            "SELECT * FROM tracked_wallets WHERE chat_id = ? ORDER BY is_active DESC, created_at DESC",
            (chat_id,),
        )
        rows = await cursor.fetchall()
        keys = rows[0].keys() if rows else []
        return [
            TrackedWallet(
                id=row["id"],
                chat_id=row["chat_id"],
                wallet_address=row["wallet_address"],
                label=row["label"],
                min_usd=row["min_usd"] or 0.0,
                is_active=bool(row["is_active"]) if "is_active" in keys else True,
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def get_all_tracked_addresses(self) -> list[str]:
        """Get all unique wallet addresses being tracked by any user (active only)."""
        cursor = await self._conn.execute(
            "SELECT DISTINCT wallet_address FROM tracked_wallets WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [row["wallet_address"] for row in rows]

    async def get_users_tracking_wallet(self, address: str) -> list[tuple[int, Optional[str], float]]:
        """Get all users actively tracking a specific wallet. Returns (chat_id, label, min_usd) tuples."""
        address = address.lower()
        cursor = await self._conn.execute(
            "SELECT chat_id, label, min_usd FROM tracked_wallets WHERE wallet_address = ? AND is_active = 1",
            (address,),
        )
        rows = await cursor.fetchall()
        return [(row["chat_id"], row["label"], row["min_usd"] or 0.0) for row in rows]

    async def pause_wallet(self, chat_id: int, address: str) -> bool:
        """Pause tracking for a wallet (set is_active=0)."""
        address = address.lower()
        cursor = await self._conn.execute(
            "UPDATE tracked_wallets SET is_active = 0 WHERE chat_id = ? AND wallet_address = ?",
            (chat_id, address),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def resume_wallet(self, chat_id: int, address: str) -> bool:
        """Resume tracking for a wallet (set is_active=1)."""
        address = address.lower()
        cursor = await self._conn.execute(
            "UPDATE tracked_wallets SET is_active = 1 WHERE chat_id = ? AND wallet_address = ?",
            (chat_id, address),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    # Trade processing
    async def is_trade_processed(self, trade_id: str) -> bool:
        cursor = await self._conn.execute(
            "SELECT 1 FROM processed_trades WHERE trade_id = ?", (trade_id,)
        )
        return await cursor.fetchone() is not None

    async def mark_trade_processed(self, trade_id: str, wallet_address: str) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO processed_trades (trade_id, wallet_address) VALUES (?, ?)",
            (trade_id, wallet_address.lower()),
        )
        await self._conn.commit()

    async def cleanup_old_trades(self, days: int = 7) -> int:
        """Remove processed trades older than N days."""
        cursor = await self._conn.execute(
            """
            DELETE FROM processed_trades
            WHERE processed_at < datetime('now', ? || ' days')
            """,
            (f"-{days}",),
        )
        await self._conn.commit()
        return cursor.rowcount

    # Subscription operations
    async def get_subscription(self, chat_id: int) -> Subscription:
        """Get user subscription settings. Returns defaults if not set."""
        cursor = await self._conn.execute(
            "SELECT * FROM subscriptions WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        if row:
            keys = row.keys()
            cat_data = row["categories"] if "categories" in keys else None
            categories = json.loads(cat_data) if cat_data else []
            return Subscription(
                chat_id=row["chat_id"],
                min_usd=row["min_usd"] or 0,
                max_usd=row["max_usd"],
                side=row["side"],
                categories=categories,
                insider_alert=bool(row["insider_alert"]) if "insider_alert" in keys else False,
                insider_min_usd=row["insider_min_usd"] if "insider_min_usd" in keys else 10000,
                insider_max_trades=row["insider_max_trades"] if "insider_max_trades" in keys else 3,
                whale_alert=bool(row["whale_alert"]) if "whale_alert" in keys else False,
                whale_min_usd=row["whale_min_usd"] if "whale_min_usd" in keys else 10000,
            )
        return Subscription(chat_id=chat_id)

    async def set_subscription(self, sub: Subscription) -> None:
        """Save user subscription settings."""
        categories_json = json.dumps(sub.categories) if sub.categories else None
        await self._conn.execute(
            """
            INSERT INTO subscriptions (chat_id, min_usd, max_usd, side, categories,
                insider_alert, insider_min_usd, insider_max_trades, whale_alert, whale_min_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                min_usd = ?, max_usd = ?, side = ?, categories = ?,
                insider_alert = ?, insider_min_usd = ?, insider_max_trades = ?,
                whale_alert = ?, whale_min_usd = ?
            """,
            (sub.chat_id, sub.min_usd, sub.max_usd, sub.side, categories_json,
             sub.insider_alert, sub.insider_min_usd, sub.insider_max_trades,
             sub.whale_alert, sub.whale_min_usd,
             sub.min_usd, sub.max_usd, sub.side, categories_json,
             sub.insider_alert, sub.insider_min_usd, sub.insider_max_trades,
             sub.whale_alert, sub.whale_min_usd),
        )
        await self._conn.commit()

    async def update_subscription_field(self, chat_id: int, field: str, value) -> None:
        """Update a single subscription field."""
        sub = await self.get_subscription(chat_id)
        setattr(sub, field, value)
        await self.set_subscription(sub)

    async def add_category(self, chat_id: int, category: str) -> bool:
        """Add a category to subscription. Returns True if added, False if already exists."""
        sub = await self.get_subscription(chat_id)
        category_lower = category.lower()
        if category_lower not in [c.lower() for c in sub.categories]:
            sub.categories.append(category)
            await self.set_subscription(sub)
            return True
        return False

    async def remove_category(self, chat_id: int, category: str) -> bool:
        """Remove a category from subscription. Returns True if removed."""
        sub = await self.get_subscription(chat_id)
        category_lower = category.lower()
        for i, c in enumerate(sub.categories):
            if c.lower() == category_lower:
                sub.categories.pop(i)
                await self.set_subscription(sub)
                return True
        return False

    async def clear_categories(self, chat_id: int) -> None:
        """Clear all categories from subscription."""
        sub = await self.get_subscription(chat_id)
        sub.categories = []
        await self.set_subscription(sub)


# Global database instance
db = Database()
