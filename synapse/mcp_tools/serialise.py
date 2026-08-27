# Copyright (c) 2026, Dxbitz and contributors
# For licence information, please see LICENSE
"""Value conversion between the database and MCP clients.

Pure stdlib, no frappe — unit testable, and cheap enough to run over every cell
of every result. Two directions:

* **Out.** date, datetime, timedelta, Decimal and bytes are not JSON safe. The
  output format is chosen per site in Synapse Settings. ISO is the default because
  it is unambiguous and it is what a model will assume; DD-MM-YYYY is offered
  because plenty of sites want their agent speaking the same dialect as the
  rest of the business.
* **In.** `to_db_date` accepts either format and returns what the database
  wants, whatever the site has chosen for output. That matters most on a
  DD-MM-YYYY site: a model doing read-modify-write hands back exactly what it
  was given, and without this every round trip would either fail or, worse,
  silently swap day and month.
"""

import datetime
import decimal
import re
from dataclasses import dataclass

__all__ = ["DMY", "ISO", "Formats", "to_client", "to_db_date"]


@dataclass(frozen=True)
class Formats:
	"""strftime patterns for one output style."""

	date: str
	datetime: str


ISO = Formats(date="%Y-%m-%d", datetime="%Y-%m-%d %H:%M:%S")
DMY = Formats(date="%d-%m-%Y", datetime="%d-%m-%Y %H:%M:%S")

# DD-MM-YYYY, optionally followed by a time. Anchored, so nothing else matches.
# A two-digit first group above 12 could only ever be a day, and ISO dates start
# with four digits, so the two forms cannot be confused for one another.
_DMY_RE = re.compile(
	r"^(?P<d>\d{2})-(?P<m>\d{2})-(?P<y>\d{4})"
	r"(?:[ T](?P<time>\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?$"
)


def to_client(value, formats: Formats = ISO):
	"""Convert one database value, or a structure of them, to something JSON can carry."""

	if isinstance(value, datetime.datetime):
		return value.strftime(formats.datetime)

	if isinstance(value, datetime.date):
		return value.strftime(formats.date)

	if isinstance(value, datetime.timedelta):
		total = int(value.total_seconds())
		return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"

	if isinstance(value, decimal.Decimal):
		return float(value)

	if isinstance(value, (bytes, bytearray)):
		return value.decode("utf-8", "replace")

	if isinstance(value, dict):
		return {k: to_client(v, formats) for k, v in value.items()}

	if isinstance(value, (list, tuple)):
		return [to_client(v, formats) for v in value]

	if isinstance(value, (str, int, float, bool)) or value is None:
		return value

	return str(value)


def to_db_date(value):
	"""Turn DD-MM-YYYY (with optional time) into ISO. Anything else is returned as is.

	Only ever called on values bound for a Date, Datetime or Time field, so a
	string that merely looks like a date elsewhere in the document is untouched.
	"""

	if not isinstance(value, str):
		return value

	match = _DMY_RE.match(value.strip())
	if not match:
		return value

	iso = f"{match['y']}-{match['m']}-{match['d']}"
	return f"{iso} {match['time']}" if match["time"] else iso
