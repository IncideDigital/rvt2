#-----------------------------------------------------------
# winver2.pl
#
#
# Change History:
#   20200731 - created
#
# copyright 2020 Quantum Analytics Research, LLC
# merge of winver and old winnt_cv
#-----------------------------------------------------------
package winver2;
use strict;

my %config = (hive          => "Software",
              osmask        => 22,
              hasShortDescr => 1,
              hasDescr      => 0,
              hasRefs       => 0,
              version       => 20200525);

sub getConfig{return %config}

sub getShortDescr {
	return "Get Windows version & build info";	
}
sub getDescr{}
sub getRefs {}
sub getHive {return $config{hive};}
sub getVersion {return $config{version};}

my $VERSION = getVersion();

sub pluginmain {
	my $class = shift;
	my $hive = shift;
	::logMsg("Launching winver2 v.".$VERSION);
	::rptMsg("winver2 v.".$VERSION); 
    ::rptMsg("(".getHive().") ".getShortDescr()."\n"); 
  
  
  my %vals = (1 => "ProductName",
              2 => "ReleaseID",
              3 => "CSDVersion",
              4 => "CurrentVersion",
              5 => "CurrentBuild",
              6 => "CurrentBuildNumber",
              7 => "InstallationType",
              8 => "EditionID",
              9 => "ProductName",
              10 => "ProductId",
              11 => "BuildLab",
              12 => "BuildLabEx",
              13 => "CompositionEditionID",
              14 => "RegisteredOrganization",
              15 => "RegisteredOwner");
         
	my $reg = Parse::Win32Registry->new($hive);
	my $root_key = $reg->get_root_key;
	my $key_path = "Microsoft\\Windows NT\\CurrentVersion";
	my $key;
	if ($key = $root_key->get_subkey($key_path)) {
        ::rptMsg($key_path);
		::rptMsg("LastWrite Time ".::getDateFromEpoch($key->get_timestamp())."Z");
		::rptMsg("");
		
		foreach my $v (sort {$a <=> $b} keys %vals) {
			
			eval {
				my $i = $key->get_value($vals{$v})->get_data();
				::rptMsg(sprintf "%-25s %-20s",$vals{$v},$i);
			};
		}
		
		eval {
			my $install = $key->get_value("InstallDate")->get_data();
			::rptMsg(sprintf "%-25s %-20s","InstallDate",::getDateFromEpoch($install)."Z");
		};
	
		eval {
			my $it = $key->get_value("InstallTime")->get_data();
			my ($t0,$t1) = unpack("VV",$it);
			my $t = ::getTime($t0,$t1);
			::rptMsg(sprintf "%-25s %-20s","InstallTime",::getDateFromEpoch($t)."Z");
		};
		
	}
	else {
		::rptMsg($key_path." not found.");
	}
}
1;
