from datetime import date, datetime
from sqlalchemy import (
    String, Integer, Float, Date, DateTime, ForeignKey, Text, Boolean, Index, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    exchange: Mapped[str] = mapped_column(String(8))  # TSX, TSXV, CSE, ASX
    name: Mapped[str] = mapped_column(String(160))
    commodity: Mapped[str] = mapped_column(String(24))  # Gold, Silver, Copper, Nickel, Lithium
    jurisdiction: Mapped[str] = mapped_column(String(64), default="")
    jurisdiction_tier: Mapped[str] = mapped_column(String(12), default="Tier 1")  # Tier 1 | High Risk
    project_name: Mapped[str] = mapped_column(String(120), default="")
    shares_outstanding: Mapped[float] = mapped_column(Float, default=0)
    resource_oz: Mapped[float | None] = mapped_column(Float, nullable=True)  # global resource, oz AuEq (or tonnes for base metals)

    prices = relationship("DailyPrice", back_populates="company")
    warrants = relationship("WarrantTranche", back_populates="company")
    financials = relationship("FinancialSnapshot", back_populates="company")
    programs = relationship("DrillProgram", back_populates="company")
    grades = relationship("DilutionGrade", back_populates="company")


class DailyPrice(Base):
    """Time-series table. In production, convert to a Timescale hypertable:
       SELECT create_hypertable('daily_prices', 'day');"""
    __tablename__ = "daily_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)

    company = relationship("Company", back_populates="prices")
    __table_args__ = (Index("ix_price_company_day", "company_id", "day", unique=True),)


class FinancialSnapshot(Base):
    """Extracted from MD&A / interim financial statements (SEDAR+/EDGAR)."""
    __tablename__ = "financial_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    cash: Mapped[float] = mapped_column(Float)                 # cash & equivalents
    monthly_burn: Mapped[float] = mapped_column(Float)          # derived or stated
    source_filing: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company = relationship("Company", back_populates="financials")


class WarrantTranche(Base):
    __tablename__ = "warrant_tranches"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="warrant")  # warrant | option
    strike: Mapped[float] = mapped_column(Float)
    expiry: Mapped[date] = mapped_column(Date)
    quantity: Mapped[float] = mapped_column(Float)
    hold_unlock: Mapped[date | None] = mapped_column(Date, nullable=True)  # 4-month hold expiry for recent PP units
    source_filing: Mapped[str] = mapped_column(String(240), default="")

    company = relationship("Company", back_populates="warrants")


class DrillProgram(Base):
    __tablename__ = "drill_programs"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Phase 1")
    announced: Mapped[date] = mapped_column(Date)
    rigs_active: Mapped[int] = mapped_column(Integer, default=1)
    planned_holes: Mapped[int] = mapped_column(Integer, default=0)
    planned_meters: Mapped[float] = mapped_column(Float, default=0)
    avg_depth_m: Mapped[float] = mapped_column(Float, default=0)
    cost_per_meter: Mapped[float] = mapped_column(Float, default=250.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    company = relationship("Company", back_populates="programs")
    results = relationship("DrillResult", back_populates="program")


class DrillResult(Base):
    """One verified intercept parsed from a press release."""
    __tablename__ = "drill_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("drill_programs.id"), nullable=True)
    published: Mapped[datetime] = mapped_column(DateTime)
    hole_id: Mapped[str] = mapped_column(String(40), default="")
    commodity: Mapped[str] = mapped_column(String(24))
    grade: Mapped[float] = mapped_column(Float)        # g/t for precious, % for base/battery
    unit: Mapped[str] = mapped_column(String(8))       # g/t | %
    width_m: Mapped[float] = mapped_column(Float)
    grade_meters: Mapped[float] = mapped_column(Float)  # grade * width
    above_benchmark: Mapped[bool] = mapped_column(Boolean, default=False)
    hit: Mapped[bool] = mapped_column(Boolean, default=True)  # intersected mineralization above cutoff
    source_url: Mapped[str] = mapped_column(String(400), default="")
    raw_sentence: Mapped[str] = mapped_column(Text, default="")

    program = relationship("DrillProgram", back_populates="results")


class PressRelease(Base):
    __tablename__ = "press_releases"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    published: Mapped[datetime] = mapped_column(DateTime, index=True)
    headline: Mapped[str] = mapped_column(String(400))
    url: Mapped[str] = mapped_column(String(400), unique=True)
    wire: Mapped[str] = mapped_column(String(40))  # GlobeNewswire, PRNewswire, Accesswire
    body: Mapped[str] = mapped_column(Text, default="")
    is_drill_start: Mapped[bool] = mapped_column(Boolean, default=False)


class InsiderBuy(Base):
    __tablename__ = "insider_buys"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    insider: Mapped[str] = mapped_column(String(120))
    shares: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    open_market: Mapped[bool] = mapped_column(Boolean, default=True)


class DilutionGrade(Base):
    """Nightly output of the ABCDF model. Keep history for trend charts."""
    __tablename__ = "dilution_grades"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    grade: Mapped[str] = mapped_column(String(2))
    cash_runway_m: Mapped[float] = mapped_column(Float)
    adjusted_runway_m: Mapped[float] = mapped_column(Float)
    upcoming_drill_cost: Mapped[float] = mapped_column(Float)
    itm_warrant_cash: Mapped[float] = mapped_column(Float)
    overhang_ratio: Mapped[float] = mapped_column(Float)  # total warrants+options / shares outstanding
    unlock_risk_pct_float: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")

    company = relationship("Company", back_populates="grades")
    __table_args__ = (Index("ix_grade_company_day", "company_id", "day", unique=True),)
