# Find uses of api.path['start_dir'] and replace with api.path.start_dir.
# See also http://crbug.com/329113288

for i in $(rg -l '\.path' . | grep -v third_party); do
  echo $i

  perl -pi -e 's/(api|self\.m).path\["start_dir"\]/$1.path.start_dir/g;' $i
  perl -pi -e "s/(api|self\.m).path\['start_dir'\]/\$1.path.start_dir/g;" $i

  perl -pi -e 's/(api|self\.m).path\["tmp_base"\]/$1.path.tmp_base_dir/g;' $i
  perl -pi -e "s/(api|self\.m).path\['tmp_base'\]/\$1.path.tmp_base_dir/g;" $i

  perl -pi -e 's/(api|self\.m).path\["cache"\]/$1.path.cache_dir/g;' $i
  perl -pi -e "s/(api|self\.m).path\['cache'\]/\$1.path.cache_dir/g;" $i

  perl -pi -e 's/(api|self\.m).path\["cleanup"\]/$1.path.cleanup_dir/g;' $i
  perl -pi -e "s/(api|self\.m).path\['cleanup'\]/\$1.path.cleanup_dir/g;" $i

  perl -pi -e 's/(api|self\.m).path\["home"\]/$1.path.home_dir/g;' $i
  perl -pi -e "s/(api|self\.m).path\['home'\]/\$1.path.home_dir/g;" $i

  perl -pi -e 's/(api|self\.m).path\["checkout"\]/$1.path.checkout_dir/g;' $i
  perl -pi -e "s/(api|self\.m).path\['checkout'\]/\$1.path.checkout_dir/g;" $i

  perl -pi -e "s/(api|self\.m).path\[([^\]'\"]+)\]/getattr(\$1.path, f'{\$2}_dir')/g;" $i
done
