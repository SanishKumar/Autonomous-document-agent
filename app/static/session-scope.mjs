// Prevent a delayed response from repainting private content after sign-out.
export class SessionScope {
  #generation = 0;

  capture() {
    const generation = this.#generation;
    return () => {
      if (generation !== this.#generation) {
        const error = new Error("The session changed before this request completed.");
        error.name = "StaleSessionError";
        throw error;
      }
    };
  }

  reset() {
    this.#generation += 1;
  }
}
