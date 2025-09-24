"""Binary matrix designer widget helpers."""
from functools import partial

import numpy as np
import ipywidgets as widgets
from IPython.display import display
from IPython import get_ipython

from py_scripts.music_utils import orient_binary_matrix

try:
    from ipycanvas import Canvas
except ImportError:
    Canvas = None

__all__ = ['binary_matrix_designer']

def binary_matrix_designer(
    rows=8,
    cols=8,
    max_size=64,
    prototype=None,
    cell_size=28,
    flip_vertical=True,
    prototype_meta=None,
    display_ui=True,
):
    """Interactive editor for binary matrices with toggle grid and free-draw canvas."""
    if Canvas is None:
        raise ImportError("ipycanvas is required for free draw mode. Install it with `pip install ipycanvas`.")

    rows = int(rows)
    cols = int(cols)
    max_size = int(max_size)

    ip = get_ipython()
    user_ns = ip.user_ns if ip else {}

    message = widgets.Output(layout=widgets.Layout(min_height='24px'))
    matrix_stats = widgets.HTML(
        value='Active cells: <b>0</b>',
        layout=widgets.Layout(min_height='24px')
    )
    grid_container = widgets.Box(layout=widgets.Layout(justify_content='center'))
    canvas_widget = Canvas(width=max(1, cols * cell_size), height=max(1, rows * cell_size), layout=widgets.Layout(border='1px solid #ccc'))

    rows_input = widgets.BoundedIntText(value=rows, min=1, max=max_size, description='Rows')
    cols_input = widgets.BoundedIntText(value=cols, min=1, max=max_size, description='Cols')
    mode_selector = widgets.ToggleButtons(
        options=[('Grid editor', 'grid'), ('Free draw', 'draw')],
        value='grid',
        tooltips=['Toggle cells individually', 'Draw with the mouse']
    )
    load_text = widgets.Text(description='Prototype', placeholder='binary_matrix_prototype', layout=widgets.Layout(width='200px'))
    load_button = widgets.Button(description='Load', tooltip='Leave blank to load the prototype argument or enter a variable name.')

    state = {
        'matrix': np.zeros((rows, cols), dtype=int),
        'toggles': [],
        'suspend_toggle': False,
        'suspend_dimension': False,
        'drawing': False,
        'draw_value': 1,
        'flip_y': bool(flip_vertical),
        'meta': (dict(prototype_meta) if prototype_meta is not None else None),
    }

    draw_hint = widgets.Label('Drag on the canvas to draw / erase')
    canvas_container = widgets.VBox([draw_hint, canvas_widget], layout=widgets.Layout(display='none', align_items='center', gap='6px'))
    grid_display = widgets.VBox([grid_container], layout=widgets.Layout(align_items='center'))
    export_selector = widgets.Dropdown(
        options=[('What you see', 'view'), ('Raw data', 'data')],
        value='view',
        description='Export'
    )
    export_button = widgets.Button(description='Export Matrix')
    clear_button = widgets.Button(description='Clear', tooltip='Set all cells to 0')

    for control in (rows_input, cols_input):
        control.layout = widgets.Layout(width='140px')
        control.style.description_width = '45px'
    mode_selector.layout = widgets.Layout(width='220px')
    mode_selector.style.button_width = '110px'
    load_text.layout.width = '240px'
    load_text.style.description_width = '80px'
    load_button.layout = widgets.Layout(width='100px')
    export_selector.layout = widgets.Layout(width='200px')
    export_button.layout = widgets.Layout(width='150px')
    clear_button.layout = widgets.Layout(width='120px')

    matrix_setup = widgets.GridBox(
        children=[rows_input, cols_input, mode_selector],
        layout=widgets.Layout(
            grid_template_columns='repeat(3, max-content)',
            grid_gap='8px 16px',
            align_items='center'
        )
    )
    prototype_controls = widgets.GridBox(
        children=[load_text, load_button],
        layout=widgets.Layout(
            grid_template_columns='minmax(240px, 1fr) max-content',
            grid_gap='8px 16px',
            align_items='center'
        )
    )
    action_controls = widgets.GridBox(
        children=[export_selector, export_button, clear_button],
        layout=widgets.Layout(
            grid_template_columns='repeat(3, max-content)',
            grid_gap='8px 16px',
            align_items='center'
        )
    )
    controls_panel = widgets.VBox(
        [
            widgets.HTML('<b>Matrix Setup</b>'),
            matrix_setup,
            widgets.HTML('<b>Prototype</b>'),
            prototype_controls,
            widgets.HTML('<b>Export & Canvas</b>'),
            action_controls,
        ],
        layout=widgets.Layout(
            gap='10px',
            padding='12px',
            border='1px solid #dddddd',
            align_items='flex-start',
            max_width='620px'
        )
    )


    def on_export(_):
        data_matrix = state['matrix']
        current_meta = state.get('meta')
        if current_meta is not None:
            view_matrix = orient_binary_matrix(data_matrix, current_meta, target_origin="upper")
        else:
            view_matrix = np.flipud(data_matrix) if state['flip_y'] else data_matrix

        user_ns['binary_matrix_ui_data'] = data_matrix
        user_ns['binary_matrix_ui_view'] = view_matrix
        if current_meta is not None:
            user_ns['binary_matrix_ui_meta'] = current_meta

        mode = export_selector.value
        to_export = view_matrix if mode == 'view' else data_matrix
        user_ns['binary_matrix_ui'] = to_export
        notify(f"Matrix exported to 'binary_matrix_ui' ({'view' if mode == 'view' else 'data'}).")

    def on_clear(_):
        r, c = state['matrix'].shape
        if r <= 0 or c <= 0:
            return
        set_matrix(np.zeros_like(state['matrix']), update_inputs=False, rebuild=False)
        notify('Canvas cleared.')

    export_button.on_click(on_export)
    clear_button.on_click(on_clear)
    def notify(text=''):
        with message:
            message.clear_output()
            if text:
                print(text)

    def resolve_to_matrix(source, silent=False):
        if source is None:
            return None
        try:
            if isinstance(source, str):
                if source in user_ns:
                    data = user_ns[source]
                else:
                    raise KeyError(f"'{source}' not found in the current namespace")
            else:
                data = source
            matrix = np.array(data)
            if matrix.ndim != 2:
                raise ValueError('Prototype must be two-dimensional')
            matrix = np.clip(matrix.astype(int), 0, 1)
            return matrix
        except Exception as err:
            if not silent:
                notify(f'Unable to load prototype: {err}')
            return None

    def view_to_data_row(view_row):
        if not state['flip_y']:
            return view_row
        return state['matrix'].shape[0] - 1 - view_row

    def data_to_view_row(data_row):
        if not state['flip_y']:
            return data_row
        return state['matrix'].shape[0] - 1 - data_row

    def render_matrix():
        matrix = state['matrix']
        active = int(np.count_nonzero(matrix))
        total = int(matrix.size)
        matrix_stats.value = f"Active cells: <b>{active}</b> / {total}"

    def update_toggle_cell(data_row, col, value):
        view_row = data_to_view_row(data_row)
        if 0 <= view_row < len(state['toggles']) and 0 <= col < len(state['toggles'][view_row]):
            state['suspend_toggle'] = True
            state['toggles'][view_row][col].value = bool(value)
            state['suspend_toggle'] = False

    def on_toggle(change, data_row, col):
        if state['suspend_toggle'] or change['name'] != 'value':
            return
        state['matrix'][data_row, col] = int(bool(change['new']))
        refresh_canvas()
        render_matrix()

    def build_grid():
        r, c = state['matrix'].shape
        state['toggles'] = []
        children = []
        for view_row in range(r):
            row_widgets = []
            data_row = view_to_data_row(view_row)
            for col in range(c):
                toggle = widgets.ToggleButton(
                    value=bool(state['matrix'][data_row, col]),
                    layout=widgets.Layout(width='28px', height='28px'),
                    tooltip=f'({data_row}, {col})'
                )
                toggle.observe(partial(on_toggle, data_row=data_row, col=col), names='value')
                row_widgets.append(toggle)
                children.append(toggle)
            state['toggles'].append(row_widgets)
        grid = widgets.GridBox(
            children=children,
            layout=widgets.Layout(
                grid_template_columns=' '.join(['28px'] * c) if c else 'auto',
                grid_gap='4px 4px',
                justify_content='center'
            )
        )
        grid_container.children = (grid,)

    def sync_toggles_with_state():
        if not state['toggles']:
            return
        r, c = state['matrix'].shape
        state['suspend_toggle'] = True
        try:
            limit_rows = min(len(state['toggles']), r)
            for view_row in range(limit_rows):
                row_widgets = state['toggles'][view_row]
                data_row = view_to_data_row(view_row)
                limit_cols = min(len(row_widgets), c)
                for col in range(limit_cols):
                    row_widgets[col].value = bool(state['matrix'][data_row, col])
        finally:
            state['suspend_toggle'] = False


    def resize_canvas():
        r, c = state['matrix'].shape
        canvas_widget.width = max(1, c * cell_size)
        canvas_widget.height = max(1, r * cell_size)

    def refresh_canvas():
        r, c = state['matrix'].shape
        canvas_widget.clear()
        canvas_widget.fill_style = '#1f77b4'
        for view_row in range(r):
            data_row = view_to_data_row(view_row)
            for col in range(c):
                if state['matrix'][data_row, col]:
                    canvas_widget.fill_rect(col * cell_size, view_row * cell_size, cell_size, cell_size)
        canvas_widget.stroke_style = '#cccccc'
        for col in range(c + 1):
            x = col * cell_size
            canvas_widget.stroke_line(x, 0, x, r * cell_size)
        for row in range(r + 1):
            y = row * cell_size
            canvas_widget.stroke_line(0, y, c * cell_size, y)

    def rebuild_interface():
        build_grid()
        resize_canvas()
        refresh_canvas()
        render_matrix()

    def set_matrix(matrix, update_inputs=True, meta_override=None, rebuild=None):
        prev_shape = state['matrix'].shape
        new_matrix = np.clip(np.array(matrix, dtype=int), 0, 1)
        state['matrix'] = new_matrix
        if meta_override is not None:
            state['meta'] = dict(meta_override)
        elif state['meta'] is None and prototype_meta is not None:
            state['meta'] = dict(prototype_meta)
        same_shape = prev_shape == new_matrix.shape
        if rebuild is None:
            rebuild = (not same_shape) or (not state['toggles'])
        elif rebuild is False and not same_shape:
            rebuild = True
        if update_inputs:
            state['suspend_dimension'] = True
            rows_input.value = new_matrix.shape[0]
            cols_input.value = new_matrix.shape[1]
            state['suspend_dimension'] = False
        if rebuild:
            rebuild_interface()
        else:
            sync_toggles_with_state()
            refresh_canvas()
            render_matrix()

    def adjust_dimensions(change):
        if state['suspend_dimension'] or change['name'] != 'value':
            return
        r = int(rows_input.value)
        c = int(cols_input.value)
        r = min(max(r, 1), max_size)
        c = min(max(c, 1), max_size)
        state['suspend_dimension'] = True
        rows_input.value = r
        cols_input.value = c
        state['suspend_dimension'] = False
        new_matrix = np.zeros((r, c), dtype=int)
        curr = state['matrix']
        min_r = min(r, curr.shape[0])
        min_c = min(c, curr.shape[1])
        new_matrix[:min_r, :min_c] = curr[:min_r, :min_c]
        set_matrix(new_matrix, update_inputs=False)

    def start_draw(x, y):
        r, c = state['matrix'].shape
        if r == 0 or c == 0:
            return None
        view_col = int(x // cell_size)
        view_row = int(y // cell_size)
        if 0 <= view_row < r and 0 <= view_col < c:
            data_row = view_to_data_row(view_row)
            current = state['matrix'][data_row, view_col]
            target = 0 if current == 1 else 1
            state['draw_value'] = target
            return data_row, view_col
        return None

    def apply_draw(x, y):
        r, c = state['matrix'].shape
        if r == 0 or c == 0:
            return
        view_col = int(x // cell_size)
        view_row = int(y // cell_size)
        if 0 <= view_row < r and 0 <= view_col < c:
            data_row = view_to_data_row(view_row)
            value = state['draw_value']
            if state['matrix'][data_row, view_col] != value:
                state['matrix'][data_row, view_col] = value
                update_toggle_cell(data_row, view_col, value)
                refresh_canvas()
                render_matrix()

    def on_canvas_down(x, y):
        cell = start_draw(x, y)
        if cell is not None:
            data_row, view_col = cell
            value = state['draw_value']
            state['matrix'][data_row, view_col] = value
            update_toggle_cell(data_row, view_col, value)
            refresh_canvas()
            render_matrix()
            state['drawing'] = True

    def on_canvas_move(x, y):
        if state['drawing']:
            apply_draw(x, y)

    def on_canvas_up(*_):
        state['drawing'] = False

    def on_mode_change(change):
        mode = change['new']
        if mode == 'draw':
            grid_display.layout.display = 'none'
            canvas_container.layout.display = ''
            refresh_canvas()
        else:
            grid_display.layout.display = ''
            canvas_container.layout.display = 'none'

    def find_candidate_meta(target_name):
        if not target_name:
            return None
        candidate_names = [f"{target_name}_meta"]
        if target_name.endswith('_df'):
            base = target_name[:-3]
            candidate_names.extend([
                f"{base}meta",
                f"{base}_meta",
            ])
        if target_name.endswith('_view'):
            base_view = target_name[:-5]
            candidate_names.extend([
                f"{base_view}_meta",
                f"{base_view}meta",
            ])
        if target_name.endswith('_data'):
            base_data = target_name[:-5]
            candidate_names.extend([
                f"{base_data}_meta",
                f"{base_data}meta",
            ])
        candidate_names.append('meta')
        seen = set()
        for name in candidate_names:
            if not name or name in seen:
                continue
            seen.add(name)
            if name in user_ns:
                candidate = user_ns[name]
                if isinstance(candidate, dict):
                    return dict(candidate)
        return None

    def on_load_click(_):
        target = load_text.value.strip()
        matrix = resolve_to_matrix(target if target else prototype)
        if matrix is not None:
            meta_override = state['meta'] if state['meta'] is not None else prototype_meta
            candidate_meta = find_candidate_meta(target)
            if candidate_meta is not None:
                matrix = orient_binary_matrix(matrix, candidate_meta, target_origin="lower")
                candidate_meta = dict(candidate_meta)
                candidate_meta['origin'] = 'lower'
                candidate_meta['row_order'] = 'low_to_high'
                meta_override = candidate_meta
            set_matrix(matrix, meta_override=meta_override)
            notify('Prototype loaded.')
        else:
            if target:
                notify(f"Prototype '{target}' was not found.")

    rows_input.observe(adjust_dimensions, names='value')
    cols_input.observe(adjust_dimensions, names='value')
    mode_selector.observe(on_mode_change, names='value')
    load_button.on_click(on_load_click)
    canvas_widget.on_mouse_down(on_canvas_down)
    canvas_widget.on_mouse_move(on_canvas_move)
    canvas_widget.on_mouse_up(on_canvas_up)
    canvas_widget.on_mouse_out(on_canvas_up)

    initial = resolve_to_matrix(prototype, silent=True)
    if initial is not None:
        set_matrix(initial, meta_override=prototype_meta)
        notify('Prototype loaded.')
    else:
        rebuild_interface()

    ui = widgets.VBox(
        [controls_panel, message, matrix_stats, grid_display, canvas_container],
        layout=widgets.Layout(gap='16px')
    )
    if display_ui:
        display(ui)
    return ui


