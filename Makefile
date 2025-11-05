IMAGE_NAME ?= ghcr.io/identitry/deepeval-mcp
TAG ?= latest
CONTAINER_NAME ?= deepeval-mcp
PLATFORMS ?= linux/amd64,linux/arm64

.PHONY: all
all: build

.PHONY: build
build:
	@echo "Building image $(IMAGE_NAME):$(TAG) for default architecture..."
	docker build -t $(IMAGE_NAME):$(TAG) .

.PHONY: buildx
buildx:
	@echo "Building multi-arch image for $(PLATFORMS)..."
	docker buildx build \
		--platform $(PLATFORMS) \
		-t $(IMAGE_NAME):$(TAG) \
		--push \
		.

.PHONY: run
run:
	@echo "Running $(CONTAINER_NAME) on port 8000..."
	docker run --rm -it \
		--name $(CONTAINER_NAME) \
		-p 8000:8000 \
		--env-file .env \
		$(IMAGE_NAME):$(TAG)

.PHONY: test
test:
	@echo "Testing health endpoint..."
	docker run --rm \
		-p 8000:8000 \
		$(IMAGE_NAME):$(TAG) \
		sh -c "sleep 2 && curl -f http://localhost:8000/health"

.PHONY: push
push:
	@echo "Pushing image $(IMAGE_NAME):$(TAG)..."
	docker push $(IMAGE_NAME):$(TAG)

.PHONY: clean
clean:
	@echo "Cleaning up unused Docker resources..."
	docker image prune -f

.PHONY: logs
logs:
	@echo "Tailing logs from $(CONTAINER_NAME)..."
	docker logs -f $(CONTAINER_NAME) || echo "Container not running."

.PHONY: stop
stop:
	@echo "Stopping container $(CONTAINER_NAME)..."
	docker stop $(CONTAINER_NAME) || true
