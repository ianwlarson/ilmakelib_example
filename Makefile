
.PHONY: all clean print release debug

release:
	@python3 buildo.py -m

all:
	@python3 buildo.py -m -t all

clean:
	@python3 buildo.py -t clean

debug:
	@python3 buildo.py -m -t debug

print:
	@python3 buildo.py -m -t print
