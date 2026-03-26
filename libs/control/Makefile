PROTO_FILE = ../../proto/runtime.proto
PROTO_OUT = pkg/proto

proto:
	@mkdir -p $(PROTO_OUT)
	protoc --go_out=$(PROTO_OUT) --go_out=paths=source_relative \
		--go-grpc_out=$(PROTO_OUT) --go-grpc_out=paths=source_relative \
		$(PROTO_FILE)