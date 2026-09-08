/* SPDX-License-Identifier: MIT */
/* A real GLES draw and readback on the Gemini render node; no display needed. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <gbm.h>
#include <xf86drm.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void fail(const char *step)
{
	fprintf(stderr, "GPU_RENDER_FAIL step=%s EGL=%#x GL=%#x\n",
		step, eglGetError(), glGetError());
	exit(1);
}

static GLuint shader(GLenum type, const char *source)
{
	GLuint s = glCreateShader(type);
	GLint ok;
	char log[4096];
	glShaderSource(s, 1, &source, NULL);
	glCompileShader(s);
	glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
	if (!ok) {
		glGetShaderInfoLog(s, sizeof(log), NULL, log);
		fprintf(stderr, "%s\n", log);
		fail("shader-compile");
	}
	return s;
}

int main(int argc, char **argv)
{
	/* Preserve the last reached boundary even if a GPU wait is killed. */
	setvbuf(stdout, NULL, _IONBF, 0);
	const char *node = argc == 2 ? argv[1] : "/dev/dri/renderD128";
	int fd = open(node, O_RDWR | O_CLOEXEC);
	if (fd < 0) { perror(node); return 1; }
	drmVersionPtr version = drmGetVersion(fd);
	if (!version || !version->name || strcmp(version->name, "panfrost")) {
		fprintf(stderr, "GPU_RENDER_FAIL: render node is not panfrost\n");
		return 1;
	}
	drmFreeVersion(version);
	struct gbm_device *gbm = gbm_create_device(fd);
	if (!gbm) fail("gbm-device");
	PFNEGLGETPLATFORMDISPLAYEXTPROC get_display =
		(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
	if (!get_display) fail("platform-display-extension");
	EGLDisplay display = get_display(EGL_PLATFORM_GBM_KHR, gbm, NULL);
	EGLint major, minor, count;
	EGLConfig config;
	const EGLint config_attrs[] = {
		EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
		EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
		EGL_ALPHA_SIZE, 8, EGL_NONE
	};
	const EGLint context_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
	if (!eglInitialize(display, &major, &minor)) fail("egl-initialize");
	if (!eglBindAPI(EGL_OPENGL_ES_API)) fail("egl-bind-api");
	if (!eglChooseConfig(display, config_attrs, &config, 1, &count) || count != 1)
		fail("egl-config");
	EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attrs);
	if (context == EGL_NO_CONTEXT) fail("egl-context");
	if (!eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context))
		fail("egl-surfaceless-current");
	const char *renderer = (const char *)glGetString(GL_RENDERER);
	printf("renderer=%s vendor=%s version=%s\n", renderer ? renderer : "NULL",
		glGetString(GL_VENDOR), glGetString(GL_VERSION));
	if (!renderer || !strstr(renderer, "Mali-T880") ||
	    strstr(renderer, "llvmpipe") || strstr(renderer, "softpipe"))
		fail("hardware-renderer-identity");

	GLuint vs = shader(GL_VERTEX_SHADER,
		"attribute vec2 position; void main() { gl_Position=vec4(position,0.,1.); }");
	GLuint fs = shader(GL_FRAGMENT_SHADER,
		"precision mediump float; uniform vec4 color; void main() { gl_FragColor=color; }");
	GLuint program = glCreateProgram();
	glAttachShader(program, vs); glAttachShader(program, fs);
	glBindAttribLocation(program, 0, "position");
	glLinkProgram(program);
	GLint linked;
	glGetProgramiv(program, GL_LINK_STATUS, &linked);
	if (!linked) fail("program-link");
	glUseProgram(program);
	GLuint texture, framebuffer, buffer;
	glGenTextures(1, &texture); glBindTexture(GL_TEXTURE_2D, texture);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 64, 64, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
	glGenFramebuffers(1, &framebuffer); glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
	if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
		fail("framebuffer");
	const GLfloat vertices[] = { -1, -1, 3, -1, -1, 3 };
	glGenBuffers(1, &buffer); glBindBuffer(GL_ARRAY_BUFFER, buffer);
	glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
	glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
	glEnableVertexAttribArray(0); glViewport(0, 0, 64, 64);
	glDisable(GL_DITHER);
	GLint color = glGetUniformLocation(program, "color");
	if (color < 0) fail("color-uniform");
	for (int pass = 0; pass < 2; pass++) {
		unsigned char pixels[64 * 64 * 4];
		/* Distinguish untouched readback storage from rendered/cleared data. */
		memset(pixels, 0xa5, sizeof(pixels));
		glClearColor(0, 0, 1, 1); glClear(GL_COLOR_BUFFER_BIT);
		glUniform4f(color, pass == 0, pass == 1, 0, 1);
		glDrawArrays(GL_TRIANGLES, 0, 3);
		glFinish();
		glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
		if (glGetError() != GL_NO_ERROR) fail("draw-readback");
		for (unsigned int i = 0; i < sizeof(pixels); i += 4)
			if (pixels[i] != (pass == 0 ? 255 : 0) ||
			    pixels[i + 1] != (pass == 1 ? 255 : 0) ||
			    pixels[i + 2] != 0 || pixels[i + 3] != 255) {
				fprintf(stderr,
					"pixel_mismatch draw=%d pixel=%u actual=%u,%u,%u,%u expected=%u,%u,0,255\n",
					pass, i / 4, pixels[i], pixels[i + 1],
					pixels[i + 2], pixels[i + 3],
					pass == 0 ? 255U : 0U, pass == 1 ? 255U : 0U);
				fail("pixel-mismatch");
			}
		printf("draw=%d pixels=4096 exact-readback=PASS\n", pass);
	}
	glDeleteBuffers(1, &buffer); glDeleteFramebuffers(1, &framebuffer);
	glDeleteTextures(1, &texture); glDeleteProgram(program);
	glDeleteShader(vs); glDeleteShader(fs);
	eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
	eglDestroyContext(display, context); eglTerminate(display);
	gbm_device_destroy(gbm); close(fd);
	puts("GPU_RENDER_PASS backend=panfrost draws=2 pixels=8192");
	return 0;
}
