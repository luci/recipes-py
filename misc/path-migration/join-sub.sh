# Find uses of path.join(...)  and replace with path.joinpath(...) or path / ...
# See also http://crbug.com/329113288

for i in $(rg -l '(cwd|path|PATH|pkg|dir|root|te?mp)\.join\(' . | grep -v third_party); do
  echo $i

  perl -pi -e 's<(%.*)([^.xt(]path|PATH|cwd|pkg|dir|root|repo|te?mp)\.join\(><$1$2.joinpath(>g;' $i
  perl -pi -e 's<([^.xt(]path|PATH|cwd|pkg|dir|root|repo|te?mp)\.join\((.*)\.join\(><$1.joinpath($2.joinpath(>g;' $i
  perl -pi -e 's<([^.xt(]path|PATH|cwd|pkg|dir|root|repo|te?mp)\.join\(([^(),*+%]+)\)><$1 / $2>g;' $i
  perl -pi -e 's<([^.xt(]path|PATH|cwd|pkg|dir|root|repo|te?mp)\.join\(><$1.joinpath(>g;' $i
done
