Module.register("MMM-DekcoBridge", {
  defaults: {
    streamUrl: "http://127.0.0.1:8089/stream.mjpg",
    width: "640px",
    retrySeconds: 5,
  },
  getStyles() { return ["MMM-DekcoBridge.css"]; },
  getDom() {
    clearTimeout(this.retryTimer);
    const wrapper = document.createElement("div");
    wrapper.className = "dekco-camera";
    wrapper.style.width = this.config.width;
    const image = document.createElement("img");
    image.alt = "Connecting to camera…";
    const address = new URL(this.config.streamUrl, window.location.href);
    if (!['http:', 'https:'].includes(address.protocol)) {
      wrapper.textContent = "Camera feed requires an HTTP or HTTPS address.";
      return wrapper;
    }
    const connect = () => {
      if (this.hidden) return;
      address.searchParams.set("reconnect", String(Date.now()));
      image.src = address.href;
    };
    image.onerror = () => {
      clearTimeout(this.retryTimer);
      image.alt = "Camera reconnecting…";
      this.retryTimer = setTimeout(connect, this.config.retrySeconds * 1000);
    };
    this.streamImage = image;
    wrapper.appendChild(image);
    connect();
    return wrapper;
  },
  suspend() {
    clearTimeout(this.retryTimer);
    if (this.streamImage) this.streamImage.removeAttribute("src");
  },
  resume() { this.updateDom(); },
});

