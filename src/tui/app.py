import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["CRAWL4AI_DISABLE_LOGGING"] = "1"

from .patch_rich import *  # noqa: F401,F403

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable, Footer, Header, Input, Label, Button, Select, Static,
    TabbedContent, TabPane, ProgressBar, TextArea,
)
from textual.reactive import reactive
from textual import work
from datetime import datetime
from pathlib import Path

from db_v2 import (
    init_db, get_connection, query_gardens, count_gardens,
    get_stats, get_distinct_values, export_to_xlsx,
    get_garden_emails, get_garden_emails_batch,
)


COLUMNS = [
    ("Name", "name", 30),
    ("Phone", "phone", 14),
    ("Email", "email", 28),
    ("District", "district", 14),
    ("State", "state", 12),
    ("Pincode", "pincode", 8),
    ("Area(ha)", "area_hectares", 10),
    ("Confidence", "confidence_score", 10),
    ("Source", "data_source", 22),
    ("Freshness", "data_freshness", 12),
]


class ExportDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, filters: dict):
        super().__init__()
        self.filters = filters

    def compose(self) -> ComposeResult:
        with Container(id="export-dialog"):
            yield Label("Export to XLSX", classes="dialog-title")
            yield Label("Export filtered results to Excel file", classes="dialog-hint")
            yield Input(
                value=f"output/tea_gardens_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                placeholder="Output file path...",
                id="export-path",
            )
            yield Horizontal(
                Button("Export", variant="primary", id="export-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons",
            )
            yield Label("", id="export-status")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-btn":
            path_input = self.query_one("#export-path", Input)
            self.query_one("#export-status", Label).update("Exporting...")
            self._do_export(path_input.value)
        else:
            self.dismiss(False)

    @work(thread=True)
    def _do_export(self, filepath: str) -> None:
        conn = get_connection()
        try:
            count = export_to_xlsx(conn, filepath, **self.filters)
            self.app.call_from_thread(
                self.query_one("#export-status", Label).update,
                f"Exported {count} records to {filepath}"
            )
            self.app.call_from_thread(self.dismiss, True)
        except Exception as e:
            self.app.call_from_thread(
                self.query_one("#export-status", Label).update,
                f"Error: {e}"
            )
        finally:
            conn.close()


class DetailScreen(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, garden: dict, all_emails: list[dict] | None = None):
        super().__init__()
        self.garden = garden
        self.all_emails = all_emails or []

    def compose(self) -> ComposeResult:
        with Container(id="detail-dialog"):
            yield Label("Garden Details", classes="dialog-title")
            text = self._format_garden()
            yield TextArea(text, read_only=True, id="detail-text")
            yield Horizontal(
                Button("Close", variant="primary", id="close-detail-btn"),
                classes="dialog-buttons",
            )

    def _format_garden(self) -> str:
        g = self.garden
        lines = []
        for key, label in [
            ("name", "Name"), ("phone", "Phone"), ("email", "Primary Email"),
            ("website", "Website"), ("address", "Address"), ("pincode", "Pincode"),
            ("district", "District"), ("state", "State"), ("town", "Town"),
            ("latitude", "Latitude"), ("longitude", "Longitude"),
            ("area_hectares", "Area (Hectares)"), ("area_bigha", "Area (Bigha)"),
            ("workforce", "Workforce"), ("category", "Category"),
            ("confidence_score", "Confidence"), ("data_source", "Data Source"),
            ("data_freshness", "Data Freshness"), ("google_url", "Google Maps URL"),
            ("rating", "Rating"), ("reviews_count", "Reviews"),
            ("created_at", "Created"), ("updated_at", "Updated"),
        ]:
            val = g.get(key)
            if val is not None:
                lines.append(f"{label:20s}: {val}")

        if self.all_emails:
            lines.append("")
            lines.append(f"{'All Emails':20s}: ({len(self.all_emails)} found)")
            for i, em in enumerate(self.all_emails, 1):
                conf = em.get("confidence", 0)
                src = em.get("source_type", "")
                lines.append(f"  {i}. {em['email']:35s}  conf={conf:.2f}  src={src}")

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


class TeaGardenTUI(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        layout: vertical;
        height: 1fr;
    }

    #stats-bar {
        dock: top;
        height: 2;
        background: $primary;
        color: $text;
        padding: 0 1;
        content-align: center middle;
    }

    #filter-bar {
        dock: top;
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    #filter-bar Input {
        width: 1fr;
        margin: 0 1;
    }

    #filter-bar Select {
        width: 16;
        margin: 0 1;
    }

    #table-container {
        height: 1fr;
    }

    DataTable {
        height: 1fr;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-darken-1;
        color: $text;
        padding: 0 1;
        content-align: center middle;
    }

    #export-dialog, #detail-dialog {
        align: center middle;
        padding: 2;
    }

    #export-dialog > Container, #detail-dialog > Container {
        width: 70;
        height: auto;
        max-height: 30;
        padding: 2;
        background: $surface;
        border: thick $primary;
    }

    .dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    .dialog-hint {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }

    .dialog-buttons {
        align: center middle;
        height: 3;
        margin-top: 1;
    }

    .dialog-buttons Button {
        margin: 0 1;
    }

    #detail-text {
        height: 18;
    }

    TabbedContent {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("e", "export", "Export XLSX", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("enter", "view_detail", "View Detail", show=True),
        Binding("f", "toggle_filter", "Filters", show=True),
    ]

    current_page = reactive(0)
    page_size = 100

    def __init__(self):
        super().__init__()
        self.db_conn = None
        self._filters = {}
        self._total_count = 0

    def on_mount(self) -> None:
        self.db_conn = init_db()
        self._load_data()

    def on_unmount(self) -> None:
        if self.db_conn:
            self.db_conn.close()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Loading...", id="stats-bar")

        with Horizontal(id="filter-bar"):
            yield Input(placeholder="Search...", id="search-input")
            yield Select(
                [("All Districts", None)] + [(d, d) for d in self._get_districts()],
                value=None,
                id="district-filter",
            )
            yield Select(
                [("All Sources", None)] + [(s, s) for s in self._get_sources()],
                value=None,
                id="source-filter",
            )
            yield Select(
                [("Any Phone", None), ("Has Phone", True), ("No Phone", False)],
                value=None,
                id="phone-filter",
            )
            yield Select(
                [("Any Email", None), ("Has Email", True), ("No Email", False)],
                value=None,
                id="email-filter",
            )

        table = DataTable(id="main-table")
        table.cursor_type = "row"
        table.zebra_stripes = True
        yield table

        yield Label("Ready", id="status-bar")
        yield Footer()

    def _get_districts(self) -> list[str]:
        try:
            conn = get_connection()
            vals = get_distinct_values(conn, "district")
            conn.close()
            return vals
        except Exception:
            return []

    def _get_sources(self) -> list[str]:
        try:
            conn = get_connection()
            vals = get_distinct_values(conn, "data_source")
            conn.close()
            return vals
        except Exception:
            return []

    def _get_filters(self) -> dict:
        filters = {}
        search = self.query_one("#search-input", Input).value.strip()
        if search:
            filters["search"] = search

        try:
            district = self.query_one("#district-filter", Select).value
            if district and district != Select.BLANK:
                filters["district"] = district
        except Exception:
            pass

        try:
            source = self.query_one("#source-filter", Select).value
            if source and source != Select.BLANK:
                filters["source"] = source
        except Exception:
            pass

        try:
            phone_val = self.query_one("#phone-filter", Select).value
            if phone_val is not None and phone_val != Select.BLANK:
                filters["has_phone"] = phone_val
        except Exception:
            pass

        try:
            email_val = self.query_one("#email-filter", Select).value
            if email_val is not None and email_val != Select.BLANK:
                filters["has_email"] = email_val
        except Exception:
            pass

        return filters

    def _load_data(self) -> None:
        if not self.db_conn:
            return

        self._filters = self._get_filters()
        self._total_count = count_gardens(self.db_conn, **self._filters)

        rows = query_gardens(
            self.db_conn,
            **self._filters,
            limit=self.page_size,
            offset=self.current_page * self.page_size,
        )

        table = self.query_one("#main-table", DataTable)
        table.clear(columns=True)

        labels = [c[0] for c in COLUMNS]
        table.add_columns(*labels)

        for row in rows:
            values = []
            for _, key, _ in COLUMNS:
                val = row.get(key)
                if val is None:
                    values.append("")
                elif key == "confidence_score":
                    values.append(f"{val:.2f}")
                elif key == "area_hectares" and val:
                    values.append(f"{val:.1f}")
                elif key == "data_freshness" and val:
                    try:
                        values.append(str(val)[:10])
                    except Exception:
                        values.append(str(val))
                else:
                    values.append(str(val))
            table.add_row(*values)

        stats = get_stats(self.db_conn)
        total_emails = self.db_conn.execute("SELECT COUNT(*) c FROM garden_emails").fetchone()["c"]
        gardens_with_email = self.db_conn.execute("SELECT COUNT(DISTINCT garden_id) c FROM garden_emails").fetchone()["c"]
        stats_text = (
            f"Total: {stats['total']} | "
            f"Phone: {stats['with_phone']} | "
            f"Emails: {total_emails} (in {gardens_with_email} gardens) | "
            f"Website: {stats['with_website']} | "
            f"Avg Confidence: {stats['avg_confidence']:.2f}"
        )
        self.query_one("#stats-bar", Label).update(stats_text)

        page_info = (
            f"Showing {len(rows)} of {self._total_count} "
            f"(Page {self.current_page + 1}) | "
            f"Filters: {self._filters or 'None'} | "
            f"[E] Export  [R] Refresh  [Enter] Detail  [F] Filters  [Q] Quit"
        )
        self.query_one("#status-bar", Label).update(page_info)

    def action_refresh(self) -> None:
        self._load_data()

    def action_export(self) -> None:
        self.push_screen(ExportDialog(self._filters))

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_toggle_filter(self) -> None:
        filter_bar = self.query_one("#filter-bar", Horizontal)
        filter_bar.display = not filter_bar.display

    def action_view_detail(self) -> None:
        table = self.query_one("#main-table", DataTable)
        try:
            row_key = table.get_row_at(table.cursor_row)
        except Exception:
            return

        offset = self.current_page * self.page_size
        rows = query_gardens(
            self.db_conn,
            **self._filters,
            limit=self.page_size,
            offset=offset,
        )

        row_idx = table.cursor_row
        if row_idx < len(rows):
            garden = rows[row_idx]
            emails = get_garden_emails(self.db_conn, garden["id"])
            self.push_screen(DetailScreen(garden, emails))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self.current_page = 0
            self._load_data()

    def on_select_changed(self, event: Select.Changed) -> None:
        self.current_page = 0
        self._load_data()

    def on_key(self, event) -> None:
        if event.key == "pagedown":
            max_page = max(0, (self._total_count - 1) // self.page_size)
            if self.current_page < max_page:
                self.current_page += 1
                self._load_data()
            event.prevent_default()
        elif event.key == "pageup":
            if self.current_page > 0:
                self.current_page -= 1
                self._load_data()
            event.prevent_default()
        elif event.key == "home":
            self.current_page = 0
            self._load_data()
            event.prevent_default()
        elif event.key == "end":
            max_page = max(0, (self._total_count - 1) // self.page_size)
            self.current_page = max_page
            self._load_data()
            event.prevent_default()


def main():
    app = TeaGardenTUI()
    app.run()


if __name__ == "__main__":
    main()
