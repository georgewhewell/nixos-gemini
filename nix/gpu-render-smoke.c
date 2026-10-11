/* SPDX-License-Identifier: MIT */
/* A real GLES draw and readback on the Gemini render node; no display needed. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <gbm.h>
#include <drm_fourcc.h>
#include <xf86drm.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MM21_WIDTH 80U
#define MM21_HEIGHT 64U
#define MM21_LUMA (MM21_WIDTH * MM21_HEIGHT)
#define MM21_RGB_TOLERANCE 2
#define MM21_ATTRIBUTE_COUNT 35U
#define DMABUF_QUERY_LIMIT 4096

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

static bool parse_fd(const char *text, int *fd)
{
	unsigned int value = 0;

	if (!text || !*text)
		return false;
	for (const char *p = text; *p; p++) {
		if (*p < '0' || *p > '9' || value > ((unsigned int)INT_MAX - (*p - '0')) / 10)
			return false;
		value = value * 10 + (*p - '0');
	}
	if (value < 3)
		return false;
	*fd = (int)value;
	return true;
}

static bool native_mm21_args(int argc, char **argv, int plane_fds[2])
{
	return argc == 5 && !strcmp(argv[2], "--native-mm21") &&
		parse_fd(argv[3], &plane_fds[0]) && parse_fd(argv[4], &plane_fds[1]) &&
		plane_fds[0] != plane_fds[1];
}

static bool has_extension(const char *list, const char *name)
{
	if (!list || !name || !*name || strchr(name, ' '))
		return false;
	size_t length = strlen(name);
	for (const char *p = list; (p = strstr(p, name)); p += length)
		if ((p == list || p[-1] == ' ') && (!p[length] || p[length] == ' '))
			return true;
	return false;
}

static void native_mm21_attributes(EGLint attributes[MM21_ATTRIBUTE_COUNT],
				   const int plane_fds[2])
{
	const EGLint values[] = {
		EGL_WIDTH, MM21_WIDTH, EGL_HEIGHT, MM21_HEIGHT,
		EGL_LINUX_DRM_FOURCC_EXT, DRM_FORMAT_NV12,
		EGL_DMA_BUF_PLANE0_FD_EXT, plane_fds[0],
		EGL_DMA_BUF_PLANE0_OFFSET_EXT, 0,
		EGL_DMA_BUF_PLANE0_PITCH_EXT, MM21_WIDTH,
		EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT, DRM_FORMAT_MOD_MTK_16L_32S_TILE & 0xffffffffu,
		EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT, DRM_FORMAT_MOD_MTK_16L_32S_TILE >> 32,
		EGL_DMA_BUF_PLANE1_FD_EXT, plane_fds[1],
		EGL_DMA_BUF_PLANE1_OFFSET_EXT, MM21_LUMA,
		EGL_DMA_BUF_PLANE1_PITCH_EXT, MM21_WIDTH,
		EGL_DMA_BUF_PLANE1_MODIFIER_LO_EXT, DRM_FORMAT_MOD_MTK_16L_32S_TILE & 0xffffffffu,
		EGL_DMA_BUF_PLANE1_MODIFIER_HI_EXT, DRM_FORMAT_MOD_MTK_16L_32S_TILE >> 32,
		EGL_YUV_COLOR_SPACE_HINT_EXT, EGL_ITU_REC601_EXT,
		EGL_SAMPLE_RANGE_HINT_EXT, EGL_YUV_NARROW_RANGE_EXT,
		EGL_YUV_CHROMA_HORIZONTAL_SITING_HINT_EXT, EGL_YUV_CHROMA_SITING_0_EXT,
		EGL_YUV_CHROMA_VERTICAL_SITING_HINT_EXT, EGL_YUV_CHROMA_SITING_0_EXT,
		EGL_NONE
	};
	_Static_assert(sizeof(values) / sizeof(values[0]) == MM21_ATTRIBUTE_COUNT,
		       "native MM21 attribute count");
	memcpy(attributes, values, sizeof(values));
}

static bool native_mm21_modifier(EGLuint64KHR modifier, EGLBoolean external_only)
{
	/* FALSE also permits this modifier with an external texture. */
	return modifier == DRM_FORMAT_MOD_MTK_16L_32S_TILE &&
		(external_only == EGL_TRUE || external_only == EGL_FALSE);
}

static void require_native_mm21(EGLDisplay display)
{
	const char *extensions = eglQueryString(display, EGL_EXTENSIONS);
	if (!has_extension(extensions, "EGL_EXT_image_dma_buf_import") ||
	    !has_extension(extensions, "EGL_EXT_image_dma_buf_import_modifiers") ||
	    !has_extension(extensions, "EGL_KHR_image_base") ||
	    !has_extension((const char *)glGetString(GL_EXTENSIONS), "GL_OES_EGL_image_external"))
		fail("native-import-extensions");
	PFNEGLQUERYDMABUFFORMATSEXTPROC query_formats =
		(PFNEGLQUERYDMABUFFORMATSEXTPROC)eglGetProcAddress("eglQueryDmaBufFormatsEXT");
	PFNEGLQUERYDMABUFMODIFIERSEXTPROC query_modifiers =
		(PFNEGLQUERYDMABUFMODIFIERSEXTPROC)eglGetProcAddress("eglQueryDmaBufModifiersEXT");
	if (!query_formats || !query_modifiers)
		fail("native-import-query-functions");
	EGLint count = 0, capacity;
	if (!query_formats(display, 0, NULL, &count) || count <= 0 || count > DMABUF_QUERY_LIMIT)
		fail("native-format-count");
	capacity = count;
	EGLint *formats = calloc(capacity, sizeof(*formats));
	if (!formats)
		fail("native-format-allocation");
	if (!query_formats(display, capacity, formats, &count) || count <= 0 || count > capacity)
		fail("native-format-query");
	bool found = false;
	for (EGLint i = 0; i < count; i++)
		found |= formats[i] == DRM_FORMAT_NV12;
	free(formats);
	if (!found)
		fail("native-nv12-format");
	if (!query_modifiers(display, DRM_FORMAT_NV12, 0, NULL, NULL, &count) ||
	    count <= 0 || count > DMABUF_QUERY_LIMIT)
		fail("native-modifier-count");
	capacity = count;
	EGLuint64KHR *modifiers = calloc(capacity, sizeof(*modifiers));
	EGLBoolean *external_only = calloc(capacity, sizeof(*external_only));
	if (!modifiers || !external_only)
		fail("native-modifier-allocation");
	if (!query_modifiers(display, DRM_FORMAT_NV12, capacity, modifiers, external_only, &count) ||
	    count <= 0 || count > capacity)
		fail("native-modifier-query");
	found = false;
	for (EGLint i = 0; i < count; i++)
		if (native_mm21_modifier(modifiers[i], external_only[i]))
			found = true;
	free(external_only);
	free(modifiers);
	if (!found)
		fail("native-mtk-external-modifier");
}

static void native_mm21_expected(unsigned int x, unsigned int y, unsigned char rgba[4])
{
	/* This oracle uses logical pixels and BT.601 narrow-range mathematics,
	 * independently of the input buffer's bytes and tiled address mapping.
	 */
	static const unsigned char palette[][3] = {
		{81, 90, 240}, {145, 54, 34}, {41, 240, 110}, {128, 128, 128}
	};
	const unsigned char *color = palette[(x / 8 + 3 * (y / 8)) % 4];
	double luma = (color[0] - 16) / 219.0;
	double cb = (color[1] - 128) / 224.0, cr = (color[2] - 128) / 224.0;
	double rgb[] = {
		luma + 1.402 * cr,
		luma - (0.114 * 1.772 / 0.587) * cb - (0.299 * 1.402 / 0.587) * cr,
		luma + 1.772 * cb
	};
	for (unsigned int i = 0; i < 3; i++) {
		double value = rgb[i] < 0 ? 0 : rgb[i] > 1 ? 1 : rgb[i];
		rgba[i] = (unsigned char)(255 * value + 0.5);
	}
	rgba[3] = 255;
}

static void check_native_mm21_pixels(const unsigned char *pixels)
{
	for (unsigned int y = 0; y < MM21_HEIGHT; y++)
		for (unsigned int x = 0; x < MM21_WIDTH; x++) {
			unsigned char expected[4];
			const unsigned char *actual = pixels + 4 * (y * MM21_WIDTH + x);
			native_mm21_expected(x, y, expected);
			if (abs(actual[0] - expected[0]) > MM21_RGB_TOLERANCE ||
			    abs(actual[1] - expected[1]) > MM21_RGB_TOLERANCE ||
			    abs(actual[2] - expected[2]) > MM21_RGB_TOLERANCE || actual[3] != 255) {
				fprintf(stderr, "native_pixel_mismatch x=%u y=%u actual=%u,%u,%u,%u expected=%u,%u,%u,%u\n",
					x, y, actual[0], actual[1], actual[2], actual[3],
					expected[0], expected[1], expected[2], expected[3]);
				fail("native-pixel-mismatch");
			}
		}
}

static void render_native_mm21(EGLDisplay display, const int plane_fds[2])
{
	require_native_mm21(display);
	PFNEGLCREATEIMAGEKHRPROC create_image =
		(PFNEGLCREATEIMAGEKHRPROC)eglGetProcAddress("eglCreateImageKHR");
	PFNEGLDESTROYIMAGEKHRPROC destroy_image =
		(PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
	PFNGLEGLIMAGETARGETTEXTURE2DOESPROC image_target =
		(PFNGLEGLIMAGETARGETTEXTURE2DOESPROC)eglGetProcAddress("glEGLImageTargetTexture2DOES");
	if (!create_image || !destroy_image || !image_target)
		fail("native-image-functions");
	EGLint attributes[MM21_ATTRIBUTE_COUNT];
	native_mm21_attributes(attributes, plane_fds);
	EGLImageKHR image = create_image(display, EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT, NULL, attributes);
	if (image == EGL_NO_IMAGE_KHR)
		fail("native-image-import");
	/* EGL owns independent references; retain no caller fd through the draw. */
	int close0 = close(plane_fds[0]), close1 = close(plane_fds[1]);
	if (close0 || close1)
		fail("native-imported-fd-close");
	puts("native-mm21=image-imported caller-fds-closed");
	GLuint source_texture, texture, framebuffer, buffer;
	glGenTextures(1, &source_texture);
	glBindTexture(GL_TEXTURE_EXTERNAL_OES, source_texture);
	glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	image_target(GL_TEXTURE_EXTERNAL_OES, (GLeglImageOES)image);
	if (glGetError() != GL_NO_ERROR)
		fail("native-image-texture");
	GLuint vs = shader(GL_VERTEX_SHADER,
		"attribute vec2 position; varying vec2 uv; void main() {"
		"gl_Position=vec4(position,0.,1.); uv=position*.5+.5; }");
	GLuint fs = shader(GL_FRAGMENT_SHADER,
		"#extension GL_OES_EGL_image_external : require\n"
		"precision mediump float; varying vec2 uv; uniform samplerExternalOES image;"
		"void main() { gl_FragColor=texture2D(image,uv); }");
	GLuint program = glCreateProgram();
	glAttachShader(program, vs); glAttachShader(program, fs);
	glBindAttribLocation(program, 0, "position");
	glLinkProgram(program);
	GLint linked;
	glGetProgramiv(program, GL_LINK_STATUS, &linked);
	if (!linked)
		fail("native-program-link");
	glUseProgram(program);
	GLint sampler = glGetUniformLocation(program, "image");
	if (sampler < 0)
		fail("native-image-uniform");
	glUniform1i(sampler, 0);
	glGenTextures(1, &texture); glBindTexture(GL_TEXTURE_2D, texture);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, MM21_WIDTH, MM21_HEIGHT, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
	glGenFramebuffers(1, &framebuffer); glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
	if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
		fail("native-framebuffer");
	const GLfloat vertices[] = {-1, -1, 3, -1, -1, 3};
	glGenBuffers(1, &buffer); glBindBuffer(GL_ARRAY_BUFFER, buffer);
	glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
	glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
	glEnableVertexAttribArray(0); glViewport(0, 0, MM21_WIDTH, MM21_HEIGHT);
	glDisable(GL_DITHER); glDisable(GL_BLEND);
	unsigned char pixels[MM21_LUMA * 4];
	memset(pixels, 0xa5, sizeof(pixels));
	glClearColor(0, 0, 1, 1); glClear(GL_COLOR_BUFFER_BIT);
	/* GL readback row0 and texture v=0 both address the fixture's first row. */
	puts("native-mm21=draw-start");
	glDrawArrays(GL_TRIANGLES, 0, 3);
	glFinish();
	glReadPixels(0, 0, MM21_WIDTH, MM21_HEIGHT, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
	if (glGetError() != GL_NO_ERROR)
		fail("native-draw-readback");
	check_native_mm21_pixels(pixels);
	glUseProgram(0);
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glBindBuffer(GL_ARRAY_BUFFER, 0);
	glBindTexture(GL_TEXTURE_EXTERNAL_OES, 0); glBindTexture(GL_TEXTURE_2D, 0);
	glDeleteBuffers(1, &buffer); glDeleteFramebuffers(1, &framebuffer);
	glDeleteTextures(1, &source_texture); glDeleteTextures(1, &texture);
	glDeleteProgram(program); glDeleteShader(vs); glDeleteShader(fs);
	if (glGetError() != GL_NO_ERROR || !destroy_image(display, image))
		fail("native-image-teardown");
}

int main(int argc, char **argv)
{
	/* Preserve the last reached boundary even if a GPU wait is killed. */
	setvbuf(stdout, NULL, _IONBF, 0);
	int plane_fds[2] = {-1, -1};
	bool native = native_mm21_args(argc, argv, plane_fds);
	if (argc != 1 && argc != 2 && !native) {
		fprintf(stderr, "Usage: %s [RENDER_NODE [--native-mm21 FD0 FD1]]\n", argv[0]);
		return 2;
	}
	if (native && (fcntl(plane_fds[0], F_GETFD) < 0 || fcntl(plane_fds[1], F_GETFD) < 0)) {
		perror("native dma-buf fd");
		return 2;
	}
	const char *node = argc >= 2 ? argv[1] : "/dev/dri/renderD128";
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
	if (native) {
		render_native_mm21(display, plane_fds);
		if (!eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT) ||
		    !eglDestroyContext(display, context) || !eglTerminate(display))
			fail("native-display-teardown");
		gbm_device_destroy(gbm);
		if (close(fd))
			fail("native-render-fd-close");
		puts("GPU_NATIVE_MM21_PASS width=80 height=64 pixels=5120 rgb_tolerance=2 imported_fds_closed=1");
		return 0;
	}

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
