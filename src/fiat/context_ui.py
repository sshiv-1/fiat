from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.formatted_text import HTML

from fiat.state import session_state

def format_tokens(t):
    if t is None:
        return "Unavailable"
    if t >= 1000000:
        return f"{t/1000000:.1f}M"
    if t >= 1000:
        return f"{t/1000:.1f}K"
    return str(t)

def show_context_ui():
    bindings = KeyBindings()
    
    # State for UI
    ui_state = {
        "selected": 0,
        "expanded": {0: True, 1: True, 2: True} # 3 sections
    }
    
    sections = ["Estimated usage", "Session", "Agent"]
    
    @bindings.add('up')
    def _(event):
        ui_state["selected"] = max(0, ui_state["selected"] - 1)
        
    @bindings.add('down')
    def _(event):
        ui_state["selected"] = min(len(sections) - 1, ui_state["selected"] + 1)
        
    @bindings.add('enter')
    def _(event):
        sel = ui_state["selected"]
        ui_state["expanded"][sel] = not ui_state["expanded"][sel]

    @bindings.add('escape')
    @bindings.add('q')
    @bindings.add('c-c')
    def _(event):
        event.app.exit()

    def get_dashboard_text():
        cw = session_state.context_window
        used = session_state.total_tokens
        
        cw_str = format_tokens(cw)
        used_str = format_tokens(used)
        
        pct = (used / cw * 100) if cw else 0
        pct_str = f"{pct:.1f}%" if cw else "Unavailable"
        
        # progress bar
        bar_len = 45
        filled = int((pct / 100) * bar_len) if cw else 0
        filled = min(bar_len, max(0, filled))
        empty = bar_len - filled
        bar = "█" * filled + "░" * empty
        
        in_pct = f"{(session_state.input_tokens / used * 100):.0f}%" if used else "0%"
        out_pct = f"{(session_state.output_tokens / used * 100):.0f}%" if used else "0%"
        tool_pct = f"{(session_state.tool_tokens / used * 100):.0f}%" if used else "0%"
        
        free = cw - used if cw else None
        free_str = format_tokens(free)
        free_pct = f"{(100 - pct):.1f}%" if cw else "Unavailable"

        cost_str = f"${session_state.estimated_cost:.4f}" if session_state.estimated_cost is not None else "Unavailable"

        lines = [
            "╭────────────────────────────────────────────────────────────────────╮",
            "│ Context Usage                                                      │",
            "│                                                                    │",
            f"│ {session_state.provider} {session_state.model}".ljust(35) + f"{used_str} / {cw_str}".rjust(34) + " │",
            f"│ {bar}  {pct_str}".ljust(69) + "│",
            "│                                                                    │"
        ]
        
        # Section 0: Estimated Usage
        sel_prefix = ">" if ui_state["selected"] == 0 else "│"
        exp_marker = "▼" if ui_state["expanded"][0] else "▶"
        lines.append(f"{sel_prefix} {exp_marker} Estimated usage".ljust(69) + "│")
        if ui_state["expanded"][0]:
            lines.extend([
                "│                                                                    │",
                f"│ ● User messages       {format_tokens(session_state.input_tokens).ljust(15)} {in_pct.ljust(23)} │",
                f"│ ● Agent responses     {format_tokens(session_state.output_tokens).ljust(15)} {out_pct.ljust(23)} │",
                f"│ ● Tool calls          {format_tokens(session_state.tool_tokens).ljust(15)} {tool_pct.ljust(23)} │",
                "│                                                                    │",
                f"│ □ Free space          {free_str.ljust(15)} {free_pct.ljust(23)} │"
            ])
            
        lines.append("│ ────────────────────────────────────────────────────────────────── │")
        
        # Section 1: Session
        sel_prefix = ">" if ui_state["selected"] == 1 else "│"
        exp_marker = "▼" if ui_state["expanded"][1] else "▶"
        lines.append(f"{sel_prefix} {exp_marker} Session".ljust(69) + "│")
        if ui_state["expanded"][1]:
            lines.extend([
                f"│   Requests             {str(session_state.requests).ljust(43)} │",
                f"│   Input                {format_tokens(session_state.input_tokens).ljust(43)} │",
                f"│   Output               {format_tokens(session_state.output_tokens).ljust(43)} │",
                f"│   Tool calls           {format_tokens(session_state.tool_tokens).ljust(43)} │",
                f"│   Estimated cost       {cost_str.ljust(43)} │"
            ])
            
        lines.append("│                                                                    │")
        
        # Section 2: Agent
        sel_prefix = ">" if ui_state["selected"] == 2 else "│"
        exp_marker = "▼" if ui_state["expanded"][2] else "▶"
        lines.append(f"{sel_prefix} {exp_marker} Agent".ljust(69) + "│")
        if ui_state["expanded"][2]:
            lines.extend([
                f"│   Status               {session_state.agent_status.ljust(43)} │",
                f"│   Current role         {session_state.current_role.ljust(43)} │",
                f"│   Iteration            {str(session_state.current_iteration)} / {str(session_state.max_iterations)}".ljust(52) + "│"
            ])

        lines.extend([
            "│                                                                    │",
            "│ ↑↓ Navigate    Enter Details    Esc Close                          │",
            "╰────────────────────────────────────────────────────────────────────╯"
        ])
        return "\n".join(lines)

    app = Application(
        layout=Layout(Window(FormattedTextControl(get_dashboard_text))),
        key_bindings=bindings,
        full_screen=True,
        refresh_interval=0.5
    )
    app.run()
