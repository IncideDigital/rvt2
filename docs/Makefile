SPHINX_HOME=../.venv/bin
SOURCE=source
OUTPUT=build

html: clean ${SPHINX_HOME}/sphinx-apidoc
	${SPHINX_HOME}/sphinx-apidoc -F -M -o ${SOURCE} ..
	${SPHINX_HOME}/sphinx-build -b html ${SOURCE} ${OUTPUT}

${SPHINX_HOME}/sphinx-apidoc:
	cd .. ; env PIPENV_VENV_IN_PROJECT=1 pipenv install -d

project:
	${SPHINX_HOME}/sphinx-apidoc -M -F -H RVT2 -A INCIDE -V 1.0 -R 1.0-alpha -o ${SOURCE} ..

clean:
	/bin/rm -rf ${OUTPUT} ${SOURCE}/Makefile ${SOURCE}/make.bat \
		${SOURCE}/_static ${SOURCE}/_templates ${SOURCE}/_build \
		${SOURCE}/plugins*rst ${SOURCE}/base.rst ${SOURCE}/rvt2.rst
