#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/fb.h>
int main(void) {
 int fd=open("/dev/fb0",O_RDONLY);struct fb_fix_screeninfo f;struct fb_var_screeninfo v;
 if(fd<0||ioctl(fd,FBIOGET_FSCREENINFO,&f)||ioctl(fd,FBIOGET_VSCREENINFO,&v))return 1;
 printf("{\"width\":%u,\"height\":%u,\"bpp\":%u,\"stride\":%u,\"bytes\":%u,\"xoffset\":%u,\"yoffset\":%u,\"red\":%u,\"green\":%u,\"blue\":%u,\"alpha\":%u,\"alpha_bits\":%u}\n",v.xres,v.yres,v.bits_per_pixel,f.line_length,f.smem_len,v.xoffset,v.yoffset,v.red.offset,v.green.offset,v.blue.offset,v.transp.offset,v.transp.length);
 close(fd);return 0;
}
