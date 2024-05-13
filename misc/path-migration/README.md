These are a collection of scripts that help repos migrate from config_types.Path
to pathlib.Path. They should be run from the recipes directory in a repository
(as configured with `recipes_path` in `infra/config/recipes.cfg`).

They do not catch everything, but they do catch most deprecated uses. There
should be a manageable number of remaining warnings after running these scripts.

See http://crbug.com/329113288 for more details.
