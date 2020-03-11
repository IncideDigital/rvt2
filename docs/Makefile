SPHINX_HOME=../.venv/bin
SOURCE=source
OUTPUT=build

html: clean ${SPHINX_HOME}/sphinx-apidoc
	${SPHINX_HOME}/sphinx-apidoc -F -M -A INCIDE -V 1.0 -R 1.0 -o ${SOURCE} ..
	${SPHINX_HOME}/sphinx-build -b html ${SOURCE} ${OUTPUT}
	# GitHub ignores directories starting with underscores. Change them
	cd ${OUTPUT}; mv _static static
	cd ${OUTPUT}; sed -i 's/_static/static/g' *.html

${SPHINX_HOME}/sphinx-apidoc:
	cd .. ; env PIPENV_VENV_IN_PROJECT=1 pipenv install -d

publish:
	make html
	cd ${OUTPUT}; git init;
	cd ${OUTPUT}; git add -A ; git commit -m 'deploy'
	cd ${OUTPUT}; git push -f git@github.com:IncideDigital/rvt2.git master:gh-pages

clean:
	/bin/rm -rf ${OUTPUT} ${SOURCE}/Makefile ${SOURCE}/make.bat \
		${SOURCE}/_static ${SOURCE}/_templates ${SOURCE}/_build \
		${SOURCE}/plugins*rst ${SOURCE}/base.rst ${SOURCE}/rvt2.rst
