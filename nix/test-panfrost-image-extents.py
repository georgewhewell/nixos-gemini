#!/usr/bin/env python3
"""Run Mesa's actual image emitter with its generated descriptor packers.

Only allocation/batch boundaries are stubbed. Import flattening, format
reinterpretation, plane helpers and descriptor packing come from the source
being built. This is a host regression, not GPU execution qualification.
"""
import argparse
import importlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def function(text, name):
    match = re.search(r"^(?:static(?: inline)? )?[^\n]+\n" + re.escape(name) + r"\(", text, re.M)
    if not match:
        raise AssertionError("missing production function " + name)
    opening = text.index("{", match.end())
    depth = 0
    for at in range(opening, len(text)):
        depth += (text[at] == "{") - (text[at] == "}")
        if not depth:
            return text[match.start():at + 1]
    raise AssertionError("unclosed production function " + name)


HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "util/format/u_format.h"
#include "pack.h"
#define DRM_FORMAT_MOD_LINEAR 0
#define DRM_FORMAT_MOD_ARM_16X16_BLOCK_U_INTERLEAVED 1
#define PIPE_BUFFER 1
#define PIPE_TEXTURE_2D 2
#define PIPE_TEXTURE_3D 3
#define PIPE_IMAGE_ACCESS_READ_WRITE 3
typedef unsigned mesa_shader_stage;
struct pipe_resource {
   unsigned target, width0, height0, depth0, array_size, nr_samples;
   enum pipe_format format;
   struct pipe_resource *next;
};
struct pan_image_extent { unsigned width, height, depth; };
struct pan_image_props {
   enum pipe_format format;
   uint64_t modifier;
   struct pan_image_extent extent_px;
   unsigned nr_samples, nr_slices, array_size;
};
struct pan_image_slice_layout {
   unsigned offset_B, size_B;
   struct { unsigned row_stride_B, surface_stride_B; } tiled_or_linear;
};
struct pan_image_layout {
   struct pan_image_slice_layout slices[4];
   unsigned array_stride_B, data_size_B;
};
struct pan_image_plane { uint64_t base; struct pan_image_layout layout; };
struct pan_image { struct pan_image_props props; struct pan_image_plane *planes[3]; };
struct pan_image_layout_constraints { unsigned wsi_row_pitch_B; bool strict; };
struct panfrost_resource {
   struct pipe_resource base;
   struct pan_image image;
   struct pan_image_plane plane;
};
struct pipe_image_view {
   struct pipe_resource *resource;
   enum pipe_format format;
   unsigned shader_access;
   union {
      struct { unsigned offset; } buf;
      struct { unsigned level, first_layer, last_layer; } tex;
   } u;
};
struct panfrost_context { struct pipe_image_view images[1][4]; unsigned image_mask[1]; };
struct panfrost_batch { struct panfrost_context *ctx; };
static unsigned tracked;
static struct panfrost_resource *pan_resource(struct pipe_resource *r) { return (void *)r; }
static void panfrost_track_image_access(struct panfrost_batch *b, unsigned s,
                                      struct pipe_image_view *v)
{ (void)b; (void)s; (void)v; tracked++; }
'''

CASES = r'''
static void init(struct panfrost_resource *r, unsigned w, unsigned h, enum pipe_format f)
{
   memset(r, 0, sizeof(*r));
   r->base = (struct pipe_resource){.target=PIPE_TEXTURE_2D, .width0=w,
      .height0=h, .depth0=1, .array_size=1, .format=f};
   r->image.props = (struct pan_image_props){.format=f,
      .extent_px={w,h,1}, .nr_samples=1, .nr_slices=4, .array_size=1};
   r->image.planes[0] = &r->plane;
   r->plane.base = 0x100000;
   r->plane.layout.array_stride_B = 0x10000;
   r->plane.layout.data_size_B = 0x40000;
   for (unsigned l=0; l<4; l++)
      r->plane.layout.slices[l] = (struct pan_image_slice_layout){
         .offset_B=l*4096, .size_B=4096,
         .tiled_or_linear={.row_stride_B=512, .surface_stride_B=4096}};
}
static struct MALI_ATTRIBUTE_BUFFER_CONTINUATION_3D
emit(struct panfrost_resource *r, unsigned level, unsigned layers,
     enum pipe_format image_format)
{
   struct panfrost_context ctx = {0};
   struct panfrost_batch batch = {.ctx=&ctx};
   struct mali_attribute_buffer_packed descriptors[8];
   memset(descriptors, 0xa5, sizeof(descriptors));
   ctx.images[0][0] = (struct pipe_image_view){.resource=&r->base,
      .format=image_format, .shader_access=PIPE_IMAGE_ACCESS_READ_WRITE,
      .u.tex={.level=level, .first_layer=0, .last_layer=layers-1}};
   ctx.image_mask[0] = 1;
   tracked=0;
   emit_image_bufs(&batch, 0, descriptors, 3);
   assert(tracked==1);
   pan_unpack(&descriptors[0], ATTRIBUTE_BUFFER, attr);
   pan_cast_and_unpack(&descriptors[1], ATTRIBUTE_BUFFER_CONTINUATION_3D, dims);
   assert(attr.pointer==r->plane.base+r->plane.layout.slices[level].offset_B);
   assert(attr.stride==util_format_get_blocksize(image_format));
   assert(attr.size==pan_image_mip_level_size(&r->image, pan_resource_plane_index(r), level));
   pan_unpack(&descriptors[2], ATTRIBUTE_BUFFER, unused);
   assert(!unused.pointer && !unused.size);
   assert(dims.row_stride==r->plane.layout.slices[level].tiled_or_linear.row_stride_B);
   return dims;
}
static int mtk(unsigned width, unsigned height, unsigned pitch, bool uv)
{
   struct panfrost_resource r, saved;
   enum pipe_format f=uv ? PIPE_FORMAT_R8G8_UNORM : PIPE_FORMAT_R8_UNORM;
   init(&r, uv ? width/2 : width, uv ? height/2 : height, f);
   struct pan_image_layout_constraints layout={.wsi_row_pitch_B=pitch, .strict=true};
   assert(adjust_mtk_tiled_props(&r, &r.image.props, 0, &layout));
   unsigned capacity=layout.wsi_row_pitch_B*r.image.props.extent_px.height;
   r.plane.layout.slices[0].size_B=capacity;
   r.plane.layout.slices[0].tiled_or_linear.row_stride_B=layout.wsi_row_pitch_B;
   panfrost_resource_change_format(&r, PIPE_FORMAT_R8G8B8A8_UINT, &saved);
   struct MALI_ATTRIBUTE_BUFFER_CONTINUATION_3D dims=emit(&r,0,1,PIPE_FORMAT_R8G8B8A8_UINT);
   unsigned tw=uv ? 8 : 16, th=uv ? 16 : 32, bytes=uv ? 2 : 1;
   unsigned rw=uv ? width/2 : width, rh=uv ? height/2 : height;
   for (unsigned y=0; y<rh; y++) for (unsigned x=0; x<rw; x+=4/bytes) {
      unsigned sx=(y%th)*(tw*bytes/4)+(x%tw)*bytes/4;
      unsigned sy=(y/th)*(pitch/(tw*bytes))+x/tw;
      if (sx>=dims.s_dimension || sy>=dims.t_dimension) {
         fprintf(stderr,"descriptor clips %s width=%u height=%u pitch=%u output=(%u,%u) source=(%u,%u) bound=(%u,%u)\n",
                 uv ? "UV" : "Y",width,height,pitch,x,y,sx,sy,dims.s_dimension,dims.t_dimension);
         return 1;
      }
      size_t address=(size_t)sy*dims.row_stride+sx*4;
      size_t expected=((size_t)(y/th)*(pitch/(tw*bytes))+x/tw)*(tw*th*bytes)+(y%th)*tw*bytes+(x%tw)*bytes;
      assert(address==expected && address+4<=capacity);
   }
   assert(dims.s_dimension==(uv ? 64 : 128));
   assert(dims.t_dimension==(pitch/16)*DIV_ROUND_UP(rh,th));
   panfrost_resource_restore_format(&r,&saved);
   assert(r.base.width0==rw && r.base.height0==rh && r.base.format==f);
   assert(r.image.props.extent_px.width==tw*th);
   return 0;
}
int main(void)
{
   /* The first case produces the exact old row5 descriptor failure. */
   if (mtk(80,64,80,false)) return 1;
   const unsigned geometry[][3]={{80,64,80},{80,96,112},{128,128,128},{16,32,32}};
   for (unsigned g=0;g<ARRAY_SIZE(geometry);g++) for (unsigned uv=0;uv<2;uv++)
      if (mtk(geometry[g][0],geometry[g][1],geometry[g][2],uv)) return 1;
   struct panfrost_resource r, other;
   for (unsigned l=0;l<4;l++) {
      init(&r,320,192,PIPE_FORMAT_R8G8B8A8_UINT);
      struct MALI_ATTRIBUTE_BUFFER_CONTINUATION_3D d=emit(&r,l,1,r.base.format);
      assert(d.s_dimension==(320u>>l) && d.t_dimension==(192u>>l) && d.r_dimension==1);
      r.image.props.format=PIPE_FORMAT_R8_G8B8_420_UNORM;
      r.image.planes[0]=&other.plane; r.image.planes[1]=&r.plane;
      r.base.width0=160; r.base.height0=96;
      d=emit(&r,l,1,PIPE_FORMAT_R8G8_UNORM);
      assert(d.s_dimension==(160u>>l) && d.t_dimension==(96u>>l));
   }
   init(&r,80,64,PIPE_FORMAT_R8G8B8A8_UINT);
   r.base.target=PIPE_TEXTURE_3D; r.image.props.extent_px.depth=8;
   struct MALI_ATTRIBUTE_BUFFER_CONTINUATION_3D d=emit(&r,1,1,r.base.format);
   assert(d.r_dimension==4 && d.slice_stride==4096);
   init(&r,80,64,PIPE_FORMAT_R8G8B8A8_UINT);
   r.base.nr_samples=r.image.props.nr_samples=4;
   r.base.array_size=r.image.props.array_size=3;
   d=emit(&r,0,3,r.base.format);
   assert(d.s_dimension==80 && d.t_dimension==64 && d.r_dimension==12 && d.slice_stride==16384);
   struct panfrost_context ctx={0}; struct panfrost_batch batch={.ctx=&ctx};
   struct mali_attribute_buffer_packed desc[2]={0};
   r.base.target=PIPE_BUFFER; r.base.width0=64;
   ctx.images[0][0]=(struct pipe_image_view){.resource=&r.base,
      .format=PIPE_FORMAT_R8G8B8A8_UINT,.shader_access=3,.u.buf={.offset=128}};
   ctx.image_mask[0]=1; emit_image_bufs(&batch,0,desc,1);
   pan_unpack(&desc[0],ATTRIBUTE_BUFFER,attr);
   assert(attr.pointer==r.plane.base+128 && attr.stride==4);
#if PAN_ARCH<=5
   pan_cast_and_unpack(&desc[1],ATTRIBUTE_BUFFER_CONTINUATION_3D,bd);
   assert(bd.s_dimension==16 && bd.t_dimension==1 && bd.r_dimension==1);
#else
   assert(attr.type==MALI_ATTRIBUTE_TYPE_1D && attr.size==64);
#endif
   puts("PANFROST_IMAGE_EXTENTS_PASS arch=" STR(PAN_ARCH));
   return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--cc', default=os.environ.get('HOSTCC', 'cc'))
    args = parser.parse_args()
    src = args.source.resolve()
    resource = (src / 'src/gallium/drivers/panfrost/pan_resource.c').read_text()
    cmdstream = (src / 'src/gallium/drivers/panfrost/pan_cmdstream.c').read_text()
    emitter = function(cmdstream, 'emit_image_bufs')
    old = re.sub(r'         const struct pan_image_props \*props = &rsrc->image.props;.*?         cfg.r_dimension =',
                 '         cfg.s_dimension = u_minify(rsrc->base.width0, level);\n'
                 '         cfg.t_dimension = u_minify(rsrc->base.height0, level);\n'
                 '         cfg.r_dimension =', emitter, count=1, flags=re.S)
    if old == emitter:
        raise AssertionError('image extent owner patch missing; old emitter must be a distinct production body')
    helpers = '\n'.join([
        function((src / 'src/gallium/drivers/panfrost/pan_resource.h').read_text(), 'pan_resource_plane_index'),
        function((src / 'src/panfrost/lib/pan_image.h').read_text(), 'pan_image_mip_level_size'),
        function(resource, 'adjust_mtk_tiled_props'),
        function(resource, 'panfrost_resource_change_format'),
        function(resource, 'panfrost_resource_restore_format'),
        function(cmdstream, 'pan_modifier_to_attr_type'),
    ])
    # Use the actual format parser/data for the small descriptor-table boundary.
    sys.path.insert(0, str(src / 'src/util/format'))
    formats = importlib.import_module('u_format_parse').parse(str(src / 'src/util/format/u_format.yaml'))
    descriptions = []
    for fmt in formats:
        if fmt.name in ('PIPE_FORMAT_R8_UNORM', 'PIPE_FORMAT_R8G8_UNORM',
                        'PIPE_FORMAT_R8G8B8A8_UINT', 'PIPE_FORMAT_R8_G8B8_420_UNORM'):
            descriptions.append('[%s]={.block={%d,%d,%d,%d},.layout=UTIL_FORMAT_LAYOUT_%s}' %
                                (fmt.name, fmt.block_width, fmt.block_height,
                                 fmt.block_depth, fmt.block_size(), fmt.layout.upper()))
    assert len(descriptions) == 4
    table = ('const struct util_format_description *util_format_description(enum pipe_format f) {\n'
             'static const struct util_format_description d[PIPE_FORMAT_COUNT] = {' + ','.join(descriptions) + '};\n'
             'assert(f < PIPE_FORMAT_COUNT && d[f].block.bits); return &d[f]; }\n')
    with tempfile.TemporaryDirectory(prefix='panfrost-image-extents-') as directory:
        temp = Path(directory)
        generated = temp / 'util/format/u_format_gen.h'
        generated.parent.mkdir(parents=True)
        with generated.open('w') as out:
            subprocess.run([sys.executable, str(src / 'src/util/format/u_format_table.py'), '--enums',
                            str(src / 'src/util/format/u_format.yaml')], stdout=out, check=True)
        for arch in (5, 7):
            with (temp / 'pack.h').open('w') as out:
                subprocess.run([sys.executable, str(src / 'src/panfrost/genxml/gen_pack.py'),
                                str(src / f'src/panfrost/genxml/v{arch}.xml')], stdout=out, check=True)
            for label, body in (('current', emitter), ('old', old)):
                path = temp / f'{arch}-{label}.c'
                path.write_text(HARNESS + '#define STR_(x) #x\n#define STR(x) STR_(x)\n' + table + helpers + body + CASES)
                executable = temp / f'{arch}-{label}'
                subprocess.run([args.cc, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                                '-Wno-unused-parameter', '-DPAN_ARCH=' + str(arch),
                                '-DHAVE_ENDIAN_H', '-DHAVE_FUNC_ATTRIBUTE_PACKED', '-DHAVE_FUNC_ATTRIBUTE_CONST',
                                '-DHAVE_FUNC_ATTRIBUTE_PURE', '-DHAVE_FUNC_ATTRIBUTE_FORMAT',
                                '-I' + str(temp), '-I' + str(src / 'include'), '-I' + str(src / 'src'),
                                '-I' + str(src / 'src/panfrost'), str(path), '-lm', '-o', str(executable)], check=True)
                result = subprocess.run([str(executable)], capture_output=True, text=True)
                if label == 'current':
                    if result.returncode:
                        raise AssertionError(result.stderr)
                    print(result.stdout.strip())
                else:
                    assert result.returncode == 1 and 'output=(0,5) source=(20,0) bound=(20,64)' in result.stderr, result
                    print('PANFROST_OLD_EMITTER_REJECTED arch=' + str(arch) + ' first_y=5')


if __name__ == '__main__':
    main()
