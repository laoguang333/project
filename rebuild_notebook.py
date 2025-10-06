import nbformat as nbf
from pathlib import Path

nb = nbf.v4.new_notebook()

nb.cells = [
    nbf.v4.new_markdown_cell("# Stealth Monitor Dashboard\n\n选择下方控件即可在办公室低调查看行情。"),
    nbf.v4.new_code_cell("""from pathlib import Path
import sys

PACKAGE_ROOT = Path('..').resolve()
PROJECT_ROOT = PACKAGE_ROOT.parent
for path in (PROJECT_ROOT, PACKAGE_ROOT):
    if str(path) not in sys.path:
        sys.path.append(str(path))"""),
    nbf.v4.new_code_cell("""from bokeh.io import output_notebook
from bokeh.resources import INLINE

output_notebook(resources=INLINE)"""),
    nbf.v4.new_code_cell("""import ipywidgets as widgets
from IPython.display import display

from stealth_monitor import INSTRUMENTS, TIMEFRAMES, CHART_STYLES, StealthDashboard

instrument_options = [(item.label, item.key) for item in INSTRUMENTS]
timeframe_options = [(item.label, item.key) for item in TIMEFRAMES]
style_options = [(item.label, item.key) for item in CHART_STYLES]

default_instrument = instrument_options[0][1]
default_timeframe = '1m'
default_style = style_options[0][1]

instrument_dropdown = widgets.Dropdown(
    options=instrument_options,
    value=default_instrument,
    description='标的:',
    layout=widgets.Layout(width='280px'),
)

timeframe_dropdown = widgets.Dropdown(
    options=timeframe_options,
    value=default_timeframe,
    description='周期:',
    layout=widgets.Layout(width='200px'),
)

style_dropdown = widgets.Dropdown(
    options=style_options,
    value=default_style,
    description='样式:',
    layout=widgets.Layout(width='200px'),
)

refresh_button = widgets.Button(description='刷新', icon='refresh', layout=widgets.Layout(width='80px'))
stop_button = widgets.Button(description='停止', icon='stop', layout=widgets.Layout(width='80px'))

controller = StealthDashboard(update_interval=10, limit=200)
chart_output = widgets.Output()
controller.bind_output(chart_output)

control_row = widgets.HBox([instrument_dropdown, timeframe_dropdown, style_dropdown], layout=widgets.Layout(gap='10px'))
action_row = widgets.HBox([refresh_button, stop_button], layout=widgets.Layout(gap='10px'))

def apply_selection(*_):
    controller.update_selection(
        instrument_dropdown.value,
        timeframe_dropdown.value,
        style_dropdown.value,
    )

def manual_refresh(_):
    controller.refresh_once()

def manual_stop(_):
    controller.stop()

instrument_dropdown.observe(apply_selection, names='value')
timeframe_dropdown.observe(apply_selection, names='value')
style_dropdown.observe(apply_selection, names='value')
refresh_button.on_click(manual_refresh)
stop_button.on_click(manual_stop)

display(control_row, action_row, chart_output)
apply_selection()"""),
    nbf.v4.new_code_cell("""# 手动停止刷新（备用）
controller.stop()"""),
]

Path('stealth_monitor/notebooks/stealth_dashboard.ipynb').write_text(nbf.writes(nb), encoding='utf-8')
