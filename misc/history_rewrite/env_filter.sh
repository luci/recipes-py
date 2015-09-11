export GIT_COMMITTER_EMAIL=`echo $GIT_COMMITTER_EMAIL | sed 's/\([^@]*@[^@]*\)@.*/\1/g'`
export GIT_AUTHOR_EMAIL=`echo $GIT_AUTHOR_EMAIL | sed 's/\([^@]*@[^@]*\)@.*/\1/g'`
