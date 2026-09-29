"""Adapter over the lab's freqtrade docker image.

The factory never imports freqtrade (GPL boundary) and never writes into
lab/user_data/strategies: generated strategies are mounted read-only via
--strategy-path from the caller's directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

BACKTEST_IMAGE = "freqtrade-lab:2026.8"
# The research image (alphalens/pyfolio) downgrades pandas and must never
# run a backtest — see lab/README.md §5.
RESEARCH_IMAGE = "freqtrade-lab:2026.8-research"


class LabError(RuntimeError):
    pass


@dataclass(frozen=True)
class Trade:
    pair: str
    open_date: str
    close_date: str
    profit_abs: float


@dataclass
class BacktestResult:
    strategy: str
    trade_count: int
    profit_total_abs: float
    profit_total: float
    trades: list[Trade] = field(repr=False)
    export_zip: Path | None = None

    def trades_digest(self) -> str:
        """Order-independent digest of (pair, open, close) triples."""
        canon = sorted((t.pair, t.open_date, t.close_date) for t in self.trades)
        return hashlib.sha256(json.dumps(canon).encode()).hexdigest()

    def to_fixture(self) -> dict:
        return {
            "strategy": self.strategy,
            "trade_count": self.trade_count,
            "profit_total_abs": self.profit_total_abs,
            "profit_total": self.profit_total,
            "trades_digest": self.trades_digest(),
            "trades": [
                [t.pair, t.open_date, t.close_date, t.profit_abs] for t in self.trades
            ],
        }


class LabEngine:
    """Runs freqtrade commands in the lab image, mirroring lab/ft's mounts."""

    def __init__(
        self,
        lab_dir: Path | None = None,
        data_dir: Path | None = None,
        image: str = BACKTEST_IMAGE,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        self.lab_dir = (lab_dir or repo_root / "lab").resolve()
        self.data_dir = (data_dir or Path.home() / "freqtrade-data").resolve()
        self.image = image
        if not (self.lab_dir / "user_data").is_dir():
            raise LabError(f"no lab user_data under {self.lab_dir}")
        if not self.data_dir.is_dir():
            raise LabError(
                f"price data missing at {self.data_dir} — run `./ft download-data` from lab/"
            )

    # -- guards ------------------------------------------------------------

    def assert_no_leftover_param_files(self) -> None:
        """user_data/strategies/<S>.json silently overrides class defaults on
        every backtest (lab/README.md §7.2). Refuse to run while any exist."""
        leftovers = sorted((self.lab_dir / "user_data" / "strategies").glob("*.json"))
        if leftovers:
            names = ", ".join(p.name for p in leftovers)
            raise LabError(
                f"leftover strategy parameter file(s) would silently override "
                f"class defaults: {names}. Remove them (or run with them "
                f"deliberately outside the factory)."
            )

    # -- execution ---------------------------------------------------------

    def _docker_cmd(self, extra_mounts: list[tuple[Path, str]] | None = None) -> list[str]:
        cmd = [
            "docker", "run", "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{self.lab_dir / 'user_data'}:/freqtrade/user_data",
            "-v", f"{self.data_dir}:/freqtrade/user_data/data",
        ]
        for host, guest in extra_mounts or []:
            cmd += ["-v", f"{host.resolve()}:{guest}:ro"]
        cmd.append(self.image)
        return cmd

    def backtest(
        self,
        strategy: str,
        timeframe: str,
        timerange: str,
        fee: float,
        config: str = "user_data/config.json",
        strategy_path: Path | None = None,
        timeout: int = 1800,
    ) -> BacktestResult:
        if self.image == RESEARCH_IMAGE:
            raise LabError("never run a backtest with the research image (pandas downgrade)")
        self.assert_no_leftover_param_files()

        results_dir = self.lab_dir / "user_data" / "backtest_results"
        before = set(results_dir.glob("*.meta.json"))

        args = [
            "backtesting",
            "--config", config,
            "--strategy", strategy,
            "--timeframe", timeframe,
            "--timerange", timerange,
            "--fee", str(fee),
            "--cache", "none",
        ]
        mounts = []
        if strategy_path is not None:
            mounts.append((strategy_path, "/factory_run"))
            args += ["--strategy-path", "/factory_run"]

        proc = subprocess.run(
            self._docker_cmd(mounts) + args,
            capture_output=True, text=True, timeout=timeout,
        )
        new_meta = set(results_dir.glob("*.meta.json")) - before
        # Assert on artifacts, never on exit status (lab/README.md §7.8) —
        # but surface stderr when the artifact is missing.
        if len(new_meta) != 1:
            raise LabError(
                f"expected exactly one new export, found {len(new_meta)} "
                f"(exit {proc.returncode}).\nstderr tail:\n{proc.stderr[-2000:]}"
            )
        return self.parse_export(new_meta.pop(), strategy)

    # -- parsing -----------------------------------------------------------

    @staticmethod
    def parse_export(meta_path: Path, strategy: str) -> BacktestResult:
        zpath = meta_path.with_name(meta_path.name.replace(".meta.json", ".zip"))
        with zipfile.ZipFile(zpath) as z:
            inner = zpath.name.replace(".zip", ".json")
            data = json.loads(z.read(inner))
        s = data["strategy"][strategy]
        trades = [
            Trade(t["pair"], t["open_date"], t["close_date"], t["profit_abs"])
            for t in s["trades"]
        ]
        return BacktestResult(
            strategy=strategy,
            trade_count=s["total_trades"],
            profit_total_abs=s["profit_total_abs"],
            profit_total=s["profit_total"],
            trades=trades,
            export_zip=zpath,
        )
