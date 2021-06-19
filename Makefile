
.PHONY: all clean print

all:
	@python3 buildo.py -m

clean:
	@python3 buildo.py -t clean

print:
	@python3 buildo.py -m -t print
