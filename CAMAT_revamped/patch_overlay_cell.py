import nbformat
from pathlib import Path

notebook_path = Path('CAMAT_revamped/tsv_to_binary.ipynb')
marker_line = '# Overlay top convolution matches on the piano roll'

with notebook_path.open('r', encoding='utf-8') as fh:
    nb = nbformat.read(fh, as_version=4)

for cell in nb.cells:
    if cell.get('cell_type') == 'code' and marker_line in ''.join(cell.get('source', '')):
        source_lines = cell['source'].splitlines()
        replacement = []
        for line in source_lines:
            if line.strip().startswith('display(pd.DataFrame(match_records)'):
                replacement.append("df_matches = pd.DataFrame(match_records)")
                replacement.append("df_matches['norm_value'] = norm_values")
                replacement.append("display(df_matches[[")
            elif line.strip() == "]])":
                # end of display call
                replacement.append("]])")
            else:
                replacement.append(line)
        cell['source'] = "\n".join(replacement)
        break
else:
    raise RuntimeError('Overlay cell not found; expected marker missing.')

with notebook_path.open('w', encoding='utf-8') as fh:
    nbformat.write(nb, fh)
