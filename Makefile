#
# The makefile is used on MacOS and Unix to compile your LaTeX files in to PDF.
#
.SUFFIXES: .tex .pdf 

NPSREPORT=npsreport
PACKAGES=packages:packages/unicode:packages/unicode/data
LATEX=pdflatex
LATEXDIFF=latexdiff
BIBTEX=bibtex
AUTH_INDEX=perl $(NPSREPORT)/authorindex.pl
FIX_ERRORS=python $(NPSREPORT)/fixerrors.py
MAKEINDEX=splitindex
INDEXFLAGS=

export TEXINPUTS := $(TEXINPUTS):$(NPSREPORT):$(PACKAGES)
export BSTINPUTS := $(BSTINPUTS):$(NPSREPORT)
export BIBINPUTS := $(BIBINPUTS):$(NPSREPORT)

TEXFILES = $(shell find . -iname "*.tex" -type f -exec echo "{}" \; | sed 's| |\\ |' | tr '\n' ' ')
ALL := report.pdf


all: $(ALL)

$(ALL): $(TEXFILES) 

#
# Build a pdf from a tex file
#
.tex.pdf:
	$(LATEX) $*
	-$(BIBTEX) $*
	$(LATEX) $*
	$(AUTH_INDEX) $*
	$(FIX_ERRORS) $*
	$(MAKEINDEX) $(INDEXFLAGS) $*
	$(LATEX) $*
	$(LATEX) $*


#
# Clean routines
#
clean:
	$(RM) *.log *.aux *.bbl *.blg  *.lof _*_.bib
	$(RM) *.lot *.toc *.out *.tmp *~ *.ain *.gz

distclean: clean
	$(RM) $(ALL)
	$(RM) revised*.pdf revised*.tex *.idx *.ilg *.ind
	$(RM) *.pyc

#
# Performs a latexdiff on the project and the backup
# Then, build the pdf of the diff
#
compare:
	for file in $(ALL:.pdf=.tex); do \
	    $(LATEXDIFF) --flatten backup/$$file $$file > revised_$$file; \
	done
	$(MAKE) $(ALL:%=revised_%)

#
# Creates a backup tarball of the project
#
backup: EXCLUDE=--exclude=packages --exclude=npsreport --exclude=doc
backup: TARBALL=backup_`date "+%Y%m%d%s"`.tar
backup:
	mkdir -p backup
	tar cf $(TARBALL) --exclude=backup $(EXCLUDE) *
	mkdir -p backup
	mv $(TARBALL) backup
	cd backup; tar xf $(TARBALL)

#
# Installs the latexdiff package
#
install-diff:
	cd packages/latexdiff; make install

.PHONY: all clean distclean
.PHONY: backup compare install-diff
