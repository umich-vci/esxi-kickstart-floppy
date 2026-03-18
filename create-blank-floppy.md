# How blank.img was created

blank.img was created on a Linux machine with the following commands:
```
# create a blank image of the appropriate size
dd if=/dev/zero of=blank.img bs=1440k count=1
# create a partition table on the floppy, detailed instructions below
parted blank.img
# create a loop device so we can format the filesystem
sudo losetup --partscan --show --find blank.img
# format the partition on the floppy as fat32 - actual loop device name may be different
sudo mkfs.vfat -F32 /dev/loop0p1
sudo losetup -d /dev/loop0
```

In `parted` the partition table was created as follows:
```
$ parted blank.img
WARNING: You are not superuser.  Watch out for permissions.
GNU Parted 3.5
Using /home/adarobin/blank.img
Welcome to GNU Parted! Type 'help' to view a list of commands.
(parted) mklabel msdos                                                    
(parted) mkpart primary fat32 0% 100%
Warning: The resulting partition is not properly aligned for best performance:
1s % 2048s != 0s
Ignore/Cancel? Ignore                                                     
(parted) p                                                                
Model:  (file)
Disk /home/adarobin/floppy.img: 1475kB
Sector size (logical/physical): 512B/512B
Partition Table: msdos
Disk Flags: 

Number  Start  End     Size    Type     File system  Flags
 1      512B   1475kB  1474kB  primary  fat32        lba

(parted) q
```
