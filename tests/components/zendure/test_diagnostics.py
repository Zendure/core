"""Tests for the Zendure diagnostics."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from homeassistant.core import HomeAssistant

from .conftest import build_snapshot

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator


@pytest.mark.usefixtures("mock_zendure")
async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_read_faults: AsyncMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test diagnostics, including a shown and a hidden active fault."""
    mock_read_faults.return_value = replace(
        build_snapshot(),
        active_faults=(6, 34),
        fault_since={6: datetime(2026, 10, 27, 7, 15, 45, tzinfo=UTC)},
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    ) == snapshot(exclude=props("created_at", "modified_at", "entry_id"))
