PROTO_FILE = ../../proto/runtime.proto
PROTO_OUT = pkg/proto

proto:
	@mkdir -p $(PROTO_OUT)
	protoc -I ../../proto \
		--go_out=$(PROTO_OUT) --go_opt=paths=source_relative \
		--go-grpc_out=$(PROTO_OUT) --go-grpc_opt=paths=source_relative \
		$(PROTO_FILE)
